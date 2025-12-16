import { useState, useEffect, useCallback } from 'react';

const BACKEND_BASE =
  (import.meta.env.VITE_BACKEND_BASE || 'http://localhost:8000').replace(/\/$/, '');
const API_BASE = `${BACKEND_BASE}/api`;

export interface DepositConfig {
  deposit_enabled: boolean;
  deposit_type: 'percentage' | 'fixed';
  deposit_percentage: number;
  deposit_fixed_amount: number;
  deposit_deadline_days: number;
}

interface DepositSettingsProps {
  onSave?: (config: DepositConfig) => void;
  initialConfig?: Partial<DepositConfig>;
  compact?: boolean;
}

const DEFAULT_CONFIG: DepositConfig = {
  deposit_enabled: false,
  deposit_type: 'percentage',
  deposit_percentage: 30,
  deposit_fixed_amount: 0,
  deposit_deadline_days: 10,
};

export default function DepositSettings({
  onSave,
  initialConfig,
  compact = false,
}: DepositSettingsProps) {
  const [config, setConfig] = useState<DepositConfig>({
    ...DEFAULT_CONFIG,
    ...initialConfig,
  });
  const [isEditing, setIsEditing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  useEffect(() => {
    const loadConfig = async () => {
      try {
        const response = await fetch(`${API_BASE}/config/global-deposit`);
        if (response.ok) {
          const data = await response.json();
          if (data && data.deposit_enabled !== undefined) {
            setConfig({
              deposit_enabled: data.deposit_enabled ?? false,
              deposit_type: data.deposit_type ?? 'percentage',
              deposit_percentage: data.deposit_percentage ?? 30,
              deposit_fixed_amount: data.deposit_fixed_amount ?? 0,
              deposit_deadline_days: data.deposit_deadline_days ?? 10,
            });
          }
        }
      } catch (err) {
        console.warn('Could not load deposit config:', err);
      }
    };
    loadConfig();
  }, []);

  const handleSave = useCallback(async () => {
    setIsSaving(true);
    setError(null);
    setSuccessMessage(null);

    try {
      const response = await fetch(`${API_BASE}/config/global-deposit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      });

      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || 'Failed to save deposit settings');
      }

      setIsEditing(false);
      setSuccessMessage('Deposit settings saved successfully');
      setTimeout(() => setSuccessMessage(null), 3000);

      if (onSave) {
        onSave(config);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save');
    } finally {
      setIsSaving(false);
    }
  }, [config, onSave]);

  const handleCancel = useCallback(() => {
    setIsEditing(false);
    setError(null);
  }, []);

  const formatCurrency = (amount: number) => {
    return `CHF ${amount.toLocaleString('de-CH', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}`;
  };

  const calculateVAT = (amount: number) => {
    const vatRate = 0.081;
    return amount * vatRate / (1 + vatRate);
  };

  if (compact && !isEditing) {
    return (
      <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg border border-gray-200">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-gray-700">Global Deposit:</span>
          {config.deposit_enabled ? (
            <span className="px-2 py-1 bg-green-100 text-green-800 text-xs rounded-full">
              {config.deposit_type === 'percentage'
                ? `${config.deposit_percentage}%`
                : formatCurrency(config.deposit_fixed_amount)}
              {' · '}{config.deposit_deadline_days} days
            </span>
          ) : (
            <span className="px-2 py-1 bg-gray-100 text-gray-600 text-xs rounded-full">
              Not configured
            </span>
          )}
        </div>
        <button
          onClick={() => setIsEditing(true)}
          className="px-3 py-1 text-xs font-medium text-blue-600 hover:text-blue-800 hover:bg-blue-50 rounded transition"
        >
          Configure
        </button>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 shadow-sm">
      <div className="p-4 border-b border-gray-200">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-800">Global Deposit Settings</h3>
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
          Default deposit applied to all offers.
        </p>
      </div>

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
        <div className="flex items-center justify-between">
          <label htmlFor="deposit-enabled" className="text-sm text-gray-700">
            Require Deposit
          </label>
          <button
            id="deposit-enabled"
            type="button"
            role="switch"
            aria-checked={config.deposit_enabled}
            disabled={!isEditing}
            onClick={() =>
              setConfig((prev) => ({ ...prev, deposit_enabled: !prev.deposit_enabled }))
            }
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
              config.deposit_enabled ? 'bg-blue-500' : 'bg-gray-300'
            } ${!isEditing ? 'opacity-60 cursor-not-allowed' : 'cursor-pointer'}`}
          >
            <span
              className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                config.deposit_enabled ? 'translate-x-6' : 'translate-x-1'
              }`}
            />
          </button>
        </div>

        {config.deposit_enabled && (
          <>
            <div>
              <label className="block text-sm text-gray-700 mb-2">Deposit Type</label>
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={!isEditing}
                  onClick={() => setConfig((prev) => ({ ...prev, deposit_type: 'percentage' }))}
                  className={`flex-1 px-3 py-2 text-xs font-medium rounded border transition ${
                    config.deposit_type === 'percentage'
                      ? 'bg-blue-50 border-blue-300 text-blue-700'
                      : 'bg-white border-gray-300 text-gray-600 hover:bg-gray-50'
                  } ${!isEditing ? 'opacity-60 cursor-not-allowed' : ''}`}
                >
                  Percentage
                </button>
                <button
                  type="button"
                  disabled={!isEditing}
                  onClick={() => setConfig((prev) => ({ ...prev, deposit_type: 'fixed' }))}
                  className={`flex-1 px-3 py-2 text-xs font-medium rounded border transition ${
                    config.deposit_type === 'fixed'
                      ? 'bg-blue-50 border-blue-300 text-blue-700'
                      : 'bg-white border-gray-300 text-gray-600 hover:bg-gray-50'
                  } ${!isEditing ? 'opacity-60 cursor-not-allowed' : ''}`}
                >
                  Fixed Amount
                </button>
              </div>
            </div>

            {config.deposit_type === 'percentage' && (
              <div>
                <label htmlFor="deposit-percentage" className="block text-sm text-gray-700 mb-1">
                  Percentage (%)
                </label>
                <input
                  id="deposit-percentage"
                  type="number"
                  min="1"
                  max="100"
                  value={config.deposit_percentage}
                  onChange={(e) =>
                    setConfig((prev) => ({
                      ...prev,
                      deposit_percentage: Math.min(100, Math.max(1, parseInt(e.target.value) || 1)),
                    }))
                  }
                  disabled={!isEditing}
                  className={`w-full px-3 py-2 text-sm border border-gray-300 rounded focus:ring-2 focus:ring-blue-500 focus:border-blue-500 ${
                    !isEditing ? 'bg-gray-100 cursor-not-allowed' : ''
                  }`}
                />
              </div>
            )}

            {config.deposit_type === 'fixed' && (
              <div>
                <label htmlFor="deposit-amount" className="block text-sm text-gray-700 mb-1">
                  Fixed Amount (CHF)
                </label>
                <div className="relative">
                  <span className="absolute left-3 top-2 text-sm text-gray-500">CHF</span>
                  <input
                    id="deposit-amount"
                    type="number"
                    min="0"
                    step="0.01"
                    value={config.deposit_fixed_amount}
                    onChange={(e) =>
                      setConfig((prev) => ({
                        ...prev,
                        deposit_fixed_amount: Math.max(0, parseFloat(e.target.value) || 0),
                      }))
                    }
                    disabled={!isEditing}
                    className={`w-full pl-12 pr-3 py-2 text-sm border border-gray-300 rounded focus:ring-2 focus:ring-blue-500 focus:border-blue-500 ${
                      !isEditing ? 'bg-gray-100 cursor-not-allowed' : ''
                    }`}
                  />
                </div>
              </div>
            )}

            <div>
              <label htmlFor="deposit-deadline" className="block text-sm text-gray-700 mb-1">
                Payment Deadline
              </label>
              <select
                id="deposit-deadline"
                value={config.deposit_deadline_days}
                onChange={(e) =>
                  setConfig((prev) => ({
                    ...prev,
                    deposit_deadline_days: parseInt(e.target.value) || 10,
                  }))
                }
                disabled={!isEditing}
                className={`w-full px-3 py-2 text-sm border border-gray-300 rounded focus:ring-2 focus:ring-blue-500 focus:border-blue-500 ${
                  !isEditing ? 'bg-gray-100 cursor-not-allowed' : ''
                }`}
              >
                <option value={7}>7 days</option>
                <option value={10}>10 days</option>
                <option value={14}>14 days</option>
                <option value={30}>30 days</option>
              </select>
            </div>

            <div className="mt-4 p-3 bg-gray-50 rounded-lg border border-gray-200">
              <div className="text-xs text-gray-500 uppercase tracking-wide mb-2">Preview</div>
              <div className="space-y-1 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-600">Deposit:</span>
                  <span className="font-medium text-gray-800">
                    {config.deposit_type === 'percentage'
                      ? `${config.deposit_percentage}% of total`
                      : formatCurrency(config.deposit_fixed_amount)}
                  </span>
                </div>
                {config.deposit_type === 'fixed' && config.deposit_fixed_amount > 0 && (
                  <div className="flex justify-between text-xs">
                    <span className="text-gray-500">VAT included (approx):</span>
                    <span className="text-gray-600">
                      {formatCurrency(calculateVAT(config.deposit_fixed_amount))}
                    </span>
                  </div>
                )}
                <div className="flex justify-between">
                  <span className="text-gray-600">Due within:</span>
                  <span className="font-medium text-gray-800">
                    {config.deposit_deadline_days} days
                  </span>
                </div>
              </div>
            </div>
          </>
        )}

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
              {isSaving ? 'Saving...' : 'Save Deposit'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
