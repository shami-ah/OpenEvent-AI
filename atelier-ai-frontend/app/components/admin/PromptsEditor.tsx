'use client';

import { useState, useEffect, useCallback } from 'react';

// Types
interface PromptConfig {
  system_prompt: string;
  step_prompts: Record<string, string>;
}

interface HistoryEntry {
  ts: string;
  config: PromptConfig;
}

const STEP_LABELS: Record<string, string> = {
  '2': 'Step 2: Date Confirmation',
  '3': 'Step 3: Room Availability',
  '4': 'Step 4: Offer',
  '5': 'Step 5: Negotiation',
  '7': 'Step 7: Confirmation',
};

export default function PromptsEditor() {
  const [config, setConfig] = useState<PromptConfig | null>(null);
  const [activeTab, setActiveTab] = useState<'system' | string>('system');
  const [saving, setSaving] = useState(false);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [notification, setNotification] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  const fetchConfig = useCallback(async () => {
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_BACKEND_BASE || ''}/api/config/prompts`);
      if (!res.ok) throw new Error('Failed to load configuration');
      const data = await res.json();
      setConfig(data);
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

  const handleSave = async () => {
    if (!config) return;
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
      setNotification({ type: 'success', message: 'Configuration saved successfully.' });
      // Refresh history if open
      if (showHistory) fetchHistory();
    } catch (err) {
      console.error(err);
      setNotification({ type: 'error', message: 'Failed to save configuration.' });
    } finally {
      setSaving(false);
    }
  };

  const handleRevert = async (index: number) => {
    if (!confirm('Are you sure you want to revert to this version? Current changes will be archived.')) return;
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_BACKEND_BASE || ''}/api/config/prompts/revert/${index}`, {
        method: 'POST',
      });
      if (!res.ok) throw new Error('Failed to revert');
      await fetchConfig();
      await fetchHistory();
      setNotification({ type: 'success', message: 'Reverted to previous version.' });
    } catch (err) {
      console.error(err);
      setNotification({ type: 'error', message: 'Failed to revert.' });
    }
  };

  const handleTextChange = (val: string) => {
    if (!config) return;
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

  if (!config) {
    return <div className="p-8 text-center text-slate-500">Loading configuration...</div>;
  }

  const activeValue = activeTab === 'system' ? config.system_prompt : config.step_prompts[activeTab] || '';

  return (
    <div className="flex flex-col h-[calc(100vh-100px)] gap-6">
      {/* Header */}
      <div className="flex items-center justify-between bg-slate-800/50 p-4 rounded-xl border border-slate-700">
        <div>
          <h2 className="text-xl font-bold text-slate-100">Workflow Configuration</h2>
          <p className="text-sm text-slate-400">Edit agent prompts and verbalization logic</p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => setShowHistory(!showHistory)}
            className={`px-4 py-2 rounded-lg text-sm font-medium border transition-colors ${
              showHistory 
                ? 'bg-slate-700 border-slate-600 text-slate-200' 
                : 'bg-transparent border-slate-700 text-slate-400 hover:text-slate-200'
            }`}
          >
            {showHistory ? 'Hide History' : 'View History'}
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

      {notification && (
        <div className={`p-4 rounded-lg border ${
          notification.type === 'success' 
            ? 'bg-green-500/10 border-green-500/20 text-green-400' 
            : 'bg-red-500/10 border-red-500/20 text-red-400'
        }`}>
          {notification.message}
        </div>
      )}

      {/* Main Content */}
      <div className="flex flex-1 gap-6 min-h-0">
        {/* Sidebar */}
        <div className="w-64 flex flex-col gap-2 overflow-y-auto">
          <button
            onClick={() => setActiveTab('system')}
            className={`text-left px-4 py-3 rounded-lg text-sm font-medium transition-colors ${
              activeTab === 'system'
                ? 'bg-blue-600/10 text-blue-400 border border-blue-600/20'
                : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
            }`}
          >
            Global System Prompt
          </button>
          <div className="h-px bg-slate-800 my-2" />
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider px-4 mb-2">
            Step Prompts
          </div>
          {Object.entries(config.step_prompts).map(([stepKey, _]) => (
            <button
              key={stepKey}
              onClick={() => setActiveTab(stepKey)}
              className={`text-left px-4 py-3 rounded-lg text-sm font-medium transition-colors ${
                activeTab === stepKey
                  ? 'bg-blue-600/10 text-blue-400 border border-blue-600/20'
                  : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
              }`}
            >
              {STEP_LABELS[stepKey] || `Step ${stepKey}`}
            </button>
          ))}
        </div>

        {/* Editor */}
        <div className="flex-1 flex flex-col bg-slate-900 rounded-xl border border-slate-700 overflow-hidden">
          <div className="bg-slate-800/50 px-4 py-3 border-b border-slate-700 flex justify-between items-center">
            <span className="text-sm font-medium text-slate-300">
              {activeTab === 'system' ? 'Global System Prompt' : STEP_LABELS[activeTab] || `Step ${activeTab}`}
            </span>
            <span className="text-xs text-slate-500">
              {activeTab === 'system' ? 'Applies to all verbalization calls' : `Context specific to Step ${activeTab}`}
            </span>
          </div>
          <textarea
            value={activeValue}
            onChange={(e) => handleTextChange(e.target.value)}
            className="flex-1 bg-transparent p-4 text-slate-300 font-mono text-sm resize-none focus:outline-none leading-relaxed"
            spellCheck={false}
          />
        </div>

        {/* History Panel */}
        {showHistory && (
          <div className="w-80 bg-slate-800/50 rounded-xl border border-slate-700 flex flex-col overflow-hidden">
            <div className="p-4 border-b border-slate-700 bg-slate-800">
              <h3 className="font-bold text-slate-200">Version History</h3>
            </div>
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              {history.length === 0 ? (
                <div className="text-sm text-slate-500 text-center">No history available.</div>
              ) : (
                history.map((entry, idx) => (
                  <div key={idx} className="bg-slate-900 border border-slate-700 rounded-lg p-3">
                    <div className="flex justify-between items-start mb-2">
                      <span className="text-xs text-slate-400 font-mono">
                        {new Date(entry.ts).toLocaleString()}
                      </span>
                      <button
                        onClick={() => handleRevert(idx)}
                        className="text-xs bg-slate-800 hover:bg-slate-700 text-blue-400 px-2 py-1 rounded border border-slate-700 transition-colors"
                      >
                        Revert
                      </button>
                    </div>
                    <div className="text-xs text-slate-500 truncate">
                      {Object.keys(entry.config.step_prompts).length} step overrides
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
