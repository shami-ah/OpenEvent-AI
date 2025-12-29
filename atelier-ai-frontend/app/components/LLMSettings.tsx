'use client';

import { useState, useEffect, useCallback } from 'react';

/**
 * LLMSettings Component
 *
 * This component allows managers to configure LLM provider settings and
 * detection pipeline configuration.
 *
 * LLM Providers (different providers for different operations):
 * - Intent classification: gemini = 75% cheaper, good accuracy
 * - Entity extraction: gemini = 75% cheaper, good structured extraction
 * - Verbalization: openai recommended for quality-critical drafts
 *
 * Pre-Filter Mode (per-message detection optimization):
 * - Enhanced: Full keyword detection, can skip LLM calls (~25% savings)
 * - Legacy: Safe fallback, always runs LLM
 *
 * INTEGRATION NOTE FOR FRONTEND INTEGRATORS:
 * ==========================================
 * Backend endpoints:
 * - /api/config/llm-provider (GET/POST)
 * - /api/config/pre-filter (GET/POST)
 */

const BACKEND_BASE =
  (process.env.NEXT_PUBLIC_BACKEND_BASE || 'http://localhost:8000').replace(/\/$/, '');
const API_BASE = `${BACKEND_BASE}/api`;

export interface LLMProviderConfig {
  intent_provider: 'openai' | 'gemini' | 'stub';
  entity_provider: 'openai' | 'gemini' | 'stub';
  verbalization_provider: 'openai' | 'gemini' | 'stub';
  source?: string;
  updated_at?: string;
}

export interface PreFilterConfig {
  mode: 'enhanced' | 'legacy';
  source?: string;
  updated_at?: string;
}

interface LLMSettingsProps {
  /** Callback when settings are saved */
  onSave?: (config: LLMProviderConfig) => void;
  /** Initial config values (optional) */
  initialConfig?: Partial<LLMProviderConfig>;
  /** Show in compact mode (inline with other settings) */
  compact?: boolean;
}

const DEFAULT_CONFIG: LLMProviderConfig = {
  intent_provider: 'gemini',      // Default: cheap, good accuracy
  entity_provider: 'gemini',      // Default: cheap, good for structured extraction
  verbalization_provider: 'openai', // Default: quality for client-facing messages
};

const PROVIDERS = [
  { value: 'openai', label: 'OpenAI', desc: 'Best quality, higher cost' },
  { value: 'gemini', label: 'Gemini', desc: '75% cheaper, good accuracy' },
  { value: 'stub', label: 'Stub', desc: 'Heuristics only, no API calls' },
] as const;

const COST_INFO = {
  openai: { intent: '$0.005', entity: '$0.008', verbal: '$0.015' },
  gemini: { intent: '$0.00125', entity: '$0.002', verbal: '$0.004' },
  stub: { intent: '$0', entity: '$0', verbal: '$0' },
};

export default function LLMSettings({
  onSave,
  initialConfig,
  compact = false,
}: LLMSettingsProps) {
  const [config, setConfig] = useState<LLMProviderConfig>({
    ...DEFAULT_CONFIG,
    ...initialConfig,
  });
  const [preFilterMode, setPreFilterMode] = useState<'enhanced' | 'legacy'>('legacy');
  const [preFilterSource, setPreFilterSource] = useState<string>('default');
  const [isEditing, setIsEditing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [configSource, setConfigSource] = useState<string>('default');

  // Load existing config from backend on mount
  useEffect(() => {
    const loadConfig = async () => {
      // Load LLM provider config
      try {
        const response = await fetch(`${API_BASE}/config/llm-provider`);
        if (response.ok) {
          const data = await response.json();
          if (data && data.intent_provider) {
            setConfig({
              intent_provider: data.intent_provider ?? 'openai',
              entity_provider: data.entity_provider ?? 'openai',
              verbalization_provider: data.verbalization_provider ?? 'openai',
            });
            setConfigSource(data.source ?? 'default');
          }
        }
      } catch (err) {
        console.warn('Could not load LLM provider config:', err);
      }

      // Load pre-filter config
      try {
        const response = await fetch(`${API_BASE}/config/pre-filter`);
        if (response.ok) {
          const data = await response.json();
          if (data && data.mode) {
            setPreFilterMode(data.mode as 'enhanced' | 'legacy');
            setPreFilterSource(data.source ?? 'default');
          }
        }
      } catch (err) {
        console.warn('Could not load pre-filter config:', err);
      }
    };
    loadConfig();
  }, []);

  const handleSave = useCallback(async () => {
    setIsSaving(true);
    setError(null);
    setSuccessMessage(null);

    try {
      // Save LLM provider config
      const providerResponse = await fetch(`${API_BASE}/config/llm-provider`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(config),
      });

      if (!providerResponse.ok) {
        const text = await providerResponse.text();
        throw new Error(text || 'Failed to save LLM provider settings');
      }

      // Save pre-filter config
      const preFilterResponse = await fetch(`${API_BASE}/config/pre-filter`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ mode: preFilterMode }),
      });

      if (!preFilterResponse.ok) {
        const text = await preFilterResponse.text();
        throw new Error(text || 'Failed to save pre-filter settings');
      }

      setIsEditing(false);
      setConfigSource('database');
      setPreFilterSource('database');
      setSuccessMessage('Settings saved successfully');
      setTimeout(() => setSuccessMessage(null), 3000);

      if (onSave) {
        onSave(config);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save');
    } finally {
      setIsSaving(false);
    }
  }, [config, preFilterMode, onSave]);

  const handleCancel = useCallback(() => {
    setIsEditing(false);
    setError(null);
  }, []);

  // Calculate estimated cost per event
  const calculateCost = () => {
    const intentCost = COST_INFO[config.intent_provider]?.intent || '$0';
    const entityCost = COST_INFO[config.entity_provider]?.entity || '$0';
    const verbalCost = COST_INFO[config.verbalization_provider]?.verbal || '$0';

    // Parse and sum
    const parsePrice = (s: string) => parseFloat(s.replace('$', '')) || 0;
    const total = parsePrice(intentCost) + parsePrice(entityCost) + parsePrice(verbalCost) * 5; // ~5 verbal calls per event

    return `~$${total.toFixed(3)}`;
  };

  // Get provider badge color
  const getBadgeColor = (provider: string) => {
    switch (provider) {
      case 'openai': return 'bg-green-100 text-green-800 border-green-300';
      case 'gemini': return 'bg-blue-100 text-blue-800 border-blue-300';
      case 'stub': return 'bg-gray-100 text-gray-600 border-gray-300';
      default: return 'bg-gray-100 text-gray-600 border-gray-300';
    }
  };

  // Detect current mode for clear display
  const getCurrentMode = (): { name: string; emoji: string; color: string; description: string } => {
    const { intent_provider, entity_provider, verbalization_provider } = config;

    // Hybrid: Gemini for detection, OpenAI for verbalization (RECOMMENDED)
    if (intent_provider === 'gemini' && entity_provider === 'gemini' && verbalization_provider === 'openai') {
      return {
        name: 'HYBRID',
        emoji: '🚀',
        color: 'bg-gradient-to-r from-blue-500 to-green-500 text-white',
        description: 'Gemini detection + OpenAI responses'
      };
    }

    // Full OpenAI
    if (intent_provider === 'openai' && entity_provider === 'openai' && verbalization_provider === 'openai') {
      return {
        name: 'OPENAI',
        emoji: '🟢',
        color: 'bg-green-500 text-white',
        description: 'Full OpenAI (highest quality)'
      };
    }

    // Full Gemini
    if (intent_provider === 'gemini' && entity_provider === 'gemini' && verbalization_provider === 'gemini') {
      return {
        name: 'GEMINI',
        emoji: '🔵',
        color: 'bg-blue-500 text-white',
        description: 'Full Gemini (lowest cost)'
      };
    }

    // Stub mode
    if (intent_provider === 'stub' && entity_provider === 'stub' && verbalization_provider === 'stub') {
      return {
        name: 'STUB',
        emoji: '🧪',
        color: 'bg-gray-500 text-white',
        description: 'Testing mode (no API calls)'
      };
    }

    // Custom configuration
    return {
      name: 'CUSTOM',
      emoji: '⚙️',
      color: 'bg-purple-500 text-white',
      description: 'Custom provider mix'
    };
  };

  const currentMode = getCurrentMode();

  if (compact && !isEditing) {
    // Compact view - clear mode indicator with details
    return (
      <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg border border-gray-200">
        <div className="flex items-center gap-3">
          {/* Main Mode Badge - Very Visible */}
          <div className={`px-3 py-1.5 text-sm font-bold rounded-lg shadow-sm ${currentMode.color}`}>
            {currentMode.emoji} {currentMode.name}
          </div>

          {/* Provider Details - Secondary */}
          <div className="flex items-center gap-1 text-xs text-gray-500">
            <span className={`px-1.5 py-0.5 rounded border ${getBadgeColor(config.intent_provider)}`} title="Intent Classification">
              I:{config.intent_provider.slice(0, 3)}
            </span>
            <span className={`px-1.5 py-0.5 rounded border ${getBadgeColor(config.entity_provider)}`} title="Entity Extraction">
              E:{config.entity_provider.slice(0, 3)}
            </span>
            <span className={`px-1.5 py-0.5 rounded border ${getBadgeColor(config.verbalization_provider)}`} title="Verbalization">
              V:{config.verbalization_provider.slice(0, 3)}
            </span>
          </div>

          {/* Pre-filter indicator */}
          <span className={`px-2 py-0.5 text-xs rounded border ${
            preFilterMode === 'enhanced'
              ? 'bg-purple-100 text-purple-700 border-purple-300'
              : 'bg-gray-100 text-gray-500 border-gray-300'
          }`} title={preFilterMode === 'enhanced' ? 'Enhanced pre-filter (faster)' : 'Legacy pre-filter (safe)'}>
            {preFilterMode === 'enhanced' ? '⚡Fast' : 'Safe'}
          </span>
        </div>
        <button
          onClick={() => setIsEditing(true)}
          className="px-3 py-1.5 text-xs font-medium text-blue-600 hover:text-blue-800 hover:bg-blue-100 rounded-lg transition border border-blue-200"
        >
          Configure
        </button>
      </div>
    );
  }

  // Quick preset handlers
  const applyPreset = (preset: 'hybrid' | 'openai' | 'gemini' | 'stub') => {
    switch (preset) {
      case 'hybrid':
        setConfig({
          intent_provider: 'gemini',
          entity_provider: 'gemini',
          verbalization_provider: 'openai',
        });
        break;
      case 'openai':
        setConfig({
          intent_provider: 'openai',
          entity_provider: 'openai',
          verbalization_provider: 'openai',
        });
        break;
      case 'gemini':
        setConfig({
          intent_provider: 'gemini',
          entity_provider: 'gemini',
          verbalization_provider: 'gemini',
        });
        break;
      case 'stub':
        setConfig({
          intent_provider: 'stub',
          entity_provider: 'stub',
          verbalization_provider: 'stub',
        });
        break;
    }
  };

  return (
    <div className="bg-white rounded-lg border border-gray-200 shadow-sm">
      <div className="p-4 border-b border-gray-200">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h3 className="text-sm font-semibold text-gray-800">
              LLM Provider Settings
            </h3>
            {/* Current Mode Badge */}
            <div className={`px-3 py-1 text-xs font-bold rounded-lg ${currentMode.color}`}>
              {currentMode.emoji} {currentMode.name}
            </div>
          </div>
          {!isEditing && (
            <button
              onClick={() => setIsEditing(true)}
              className="px-3 py-1 text-xs font-medium text-blue-600 hover:text-blue-800 hover:bg-blue-50 rounded transition"
            >
              Edit
            </button>
          )}
        </div>
        <p className="text-xs text-gray-500 mt-1">
          {currentMode.description} · Source: {configSource}
        </p>
      </div>

      {/* Quick Preset Buttons */}
      {isEditing && (
        <div className="p-4 bg-gray-50 border-b border-gray-200">
          <div className="text-xs text-gray-500 uppercase tracking-wide mb-2">Quick Presets</div>
          <div className="flex gap-2 flex-wrap">
            <button
              type="button"
              onClick={() => applyPreset('hybrid')}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg border transition ${
                currentMode.name === 'HYBRID'
                  ? 'bg-gradient-to-r from-blue-500 to-green-500 text-white border-transparent'
                  : 'bg-white border-gray-300 text-gray-700 hover:bg-gray-50'
              }`}
            >
              🚀 Hybrid (Recommended)
            </button>
            <button
              type="button"
              onClick={() => applyPreset('openai')}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg border transition ${
                currentMode.name === 'OPENAI'
                  ? 'bg-green-500 text-white border-transparent'
                  : 'bg-white border-gray-300 text-gray-700 hover:bg-gray-50'
              }`}
            >
              🟢 Full OpenAI
            </button>
            <button
              type="button"
              onClick={() => applyPreset('gemini')}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg border transition ${
                currentMode.name === 'GEMINI'
                  ? 'bg-blue-500 text-white border-transparent'
                  : 'bg-white border-gray-300 text-gray-700 hover:bg-gray-50'
              }`}
            >
              🔵 Full Gemini
            </button>
            <button
              type="button"
              onClick={() => applyPreset('stub')}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg border transition ${
                currentMode.name === 'STUB'
                  ? 'bg-gray-500 text-white border-transparent'
                  : 'bg-white border-gray-300 text-gray-700 hover:bg-gray-50'
              }`}
            >
              🧪 Stub (Testing)
            </button>
          </div>
        </div>
      )}

      {error && (
        <div className="mx-4 mt-3 p-2 bg-red-50 border border-red-200 text-red-700 text-xs rounded">
          {error}
        </div>
      )}

      {successMessage && (
        <div className="mx-4 mt-3 p-2 bg-green-50 border border-green-200 text-green-700 text-xs rounded">
          {successMessage}
        </div>
      )}

      <div className="p-4 space-y-4">
        {/* Intent Provider */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Intent Classification
            <span className="text-xs text-gray-400 ml-2">({COST_INFO[config.intent_provider]?.intent}/call)</span>
          </label>
          <div className="flex gap-2">
            {PROVIDERS.map((p) => {
              const isSelected = config.intent_provider === p.value;
              const colorClass = p.value === 'openai' ? 'bg-green-500' : p.value === 'gemini' ? 'bg-blue-500' : 'bg-gray-500';
              return (
                <button
                  key={p.value}
                  type="button"
                  disabled={!isEditing}
                  onClick={() => setConfig((prev) => ({ ...prev, intent_provider: p.value }))}
                  className={`flex-1 px-3 py-2 text-xs font-medium rounded-lg border-2 transition-all ${
                    isSelected
                      ? `${colorClass} text-white border-transparent shadow-md ring-2 ring-offset-1 ring-${p.value === 'openai' ? 'green' : p.value === 'gemini' ? 'blue' : 'gray'}-300`
                      : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50 hover:border-gray-300'
                  } ${!isEditing ? 'opacity-60 cursor-not-allowed' : ''}`}
                  title={p.desc}
                >
                  {isSelected && '✓ '}{p.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Entity Provider */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Entity Extraction
            <span className="text-xs text-gray-400 ml-2">({COST_INFO[config.entity_provider]?.entity}/call)</span>
          </label>
          <div className="flex gap-2">
            {PROVIDERS.map((p) => {
              const isSelected = config.entity_provider === p.value;
              const colorClass = p.value === 'openai' ? 'bg-green-500' : p.value === 'gemini' ? 'bg-blue-500' : 'bg-gray-500';
              return (
                <button
                  key={p.value}
                  type="button"
                  disabled={!isEditing}
                  onClick={() => setConfig((prev) => ({ ...prev, entity_provider: p.value }))}
                  className={`flex-1 px-3 py-2 text-xs font-medium rounded-lg border-2 transition-all ${
                    isSelected
                      ? `${colorClass} text-white border-transparent shadow-md ring-2 ring-offset-1 ring-${p.value === 'openai' ? 'green' : p.value === 'gemini' ? 'blue' : 'gray'}-300`
                      : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50 hover:border-gray-300'
                  } ${!isEditing ? 'opacity-60 cursor-not-allowed' : ''}`}
                  title={p.desc}
                >
                  {isSelected && '✓ '}{p.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Verbalization Provider */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Verbalization (Draft Composition)
            <span className="text-xs text-gray-400 ml-2">({COST_INFO[config.verbalization_provider]?.verbal}/call, ~5x/event)</span>
          </label>
          <div className="flex gap-2">
            {PROVIDERS.map((p) => {
              const isSelected = config.verbalization_provider === p.value;
              const colorClass = p.value === 'openai' ? 'bg-green-500' : p.value === 'gemini' ? 'bg-blue-500' : 'bg-gray-500';
              return (
                <button
                  key={p.value}
                  type="button"
                  disabled={!isEditing}
                  onClick={() => setConfig((prev) => ({ ...prev, verbalization_provider: p.value }))}
                  className={`flex-1 px-3 py-2 text-xs font-medium rounded-lg border-2 transition-all ${
                    isSelected
                      ? `${colorClass} text-white border-transparent shadow-md ring-2 ring-offset-1 ring-${p.value === 'openai' ? 'green' : p.value === 'gemini' ? 'blue' : 'gray'}-300`
                      : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50 hover:border-gray-300'
                  } ${!isEditing ? 'opacity-60 cursor-not-allowed' : ''}`}
                  title={p.desc}
                >
                  {isSelected && '✓ '}{p.label}
                </button>
              );
            })}
          </div>
          {config.verbalization_provider !== 'openai' && (
            <p className="mt-1 text-xs text-amber-600">
              OpenAI recommended for verbalization quality
            </p>
          )}
        </div>

        {/* Pre-Filter Mode */}
        <div className="pt-4 border-t border-gray-200">
          <label className="block text-sm text-gray-700 mb-2">
            Pre-Filter Mode
            <span className="text-xs text-gray-400 ml-2">(per-message optimization)</span>
          </label>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={!isEditing}
              onClick={() => setPreFilterMode('legacy')}
              className={`flex-1 px-3 py-2 text-xs font-medium rounded border transition ${
                preFilterMode === 'legacy'
                  ? 'bg-gray-100 border-gray-400 text-gray-700'
                  : 'bg-white border-gray-300 text-gray-600 hover:bg-gray-50'
              } ${!isEditing ? 'opacity-60 cursor-not-allowed' : ''}`}
              title="Safe fallback - always runs LLM"
            >
              Legacy (Safe)
            </button>
            <button
              type="button"
              disabled={!isEditing}
              onClick={() => setPreFilterMode('enhanced')}
              className={`flex-1 px-3 py-2 text-xs font-medium rounded border transition ${
                preFilterMode === 'enhanced'
                  ? 'bg-purple-50 border-purple-300 text-purple-700'
                  : 'bg-white border-gray-300 text-gray-600 hover:bg-gray-50'
              } ${!isEditing ? 'opacity-60 cursor-not-allowed' : ''}`}
              title="Full keyword detection - can skip LLM calls"
            >
              Enhanced (~25% savings)
            </button>
          </div>
          <p className="mt-2 text-xs text-gray-500">
            {preFilterMode === 'enhanced' ? (
              <>Keyword detection runs before LLM. Skips ~25% of intent calls for confirmations.</>
            ) : (
              <>Safe mode: Always runs LLM for intent classification. Use if enhanced causes issues.</>
            )}
          </p>
          <p className="text-xs text-gray-400 mt-1">Source: {preFilterSource}</p>
        </div>

        {/* Cost Preview */}
        <div className="mt-4 p-3 bg-gray-50 rounded-lg border border-gray-200">
          <div className="text-xs text-gray-500 uppercase tracking-wide mb-2">Cost Estimate</div>
          <div className="flex justify-between text-sm">
            <span className="text-gray-600">Per Event:</span>
            <span className="font-medium text-gray-800">{calculateCost()}</span>
          </div>
          <div className="mt-2 text-xs text-gray-500">
            {config.intent_provider === 'gemini' && config.entity_provider === 'gemini' && (
              <span className="text-green-600">
                Saving ~75% on classification costs
                {preFilterMode === 'enhanced' && ' + ~25% from pre-filter optimization'}
              </span>
            )}
            {config.intent_provider === 'openai' && config.entity_provider === 'openai' && config.verbalization_provider === 'openai' && (
              <span>Full OpenAI - best quality</span>
            )}
            {preFilterMode === 'enhanced' && config.intent_provider !== 'gemini' && (
              <span className="text-purple-600">Pre-filter enabled: ~25% fewer intent calls</span>
            )}
          </div>
        </div>

        {/* Gemini API Key Notice */}
        {(config.intent_provider === 'gemini' || config.entity_provider === 'gemini' || config.verbalization_provider === 'gemini') && (
          <div className="p-3 bg-blue-50 rounded-lg border border-blue-200">
            <p className="text-xs text-blue-700">
              <strong>Note:</strong> Gemini requires <code className="bg-blue-100 px-1 rounded">GOOGLE_API_KEY</code> environment variable.
              Get your key at <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener noreferrer" className="underline">aistudio.google.com</a>
            </p>
          </div>
        )}

        {/* Action Buttons */}
        {isEditing && (
          <div className="flex gap-2 pt-2 border-t border-gray-200">
            <button
              onClick={handleCancel}
              disabled={isSaving}
              className="flex-1 px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded hover:bg-gray-50 transition disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={isSaving}
              className="flex-1 px-4 py-2 text-sm font-medium text-white bg-blue-500 rounded hover:bg-blue-600 transition disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isSaving ? 'Saving...' : 'Save Settings'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
