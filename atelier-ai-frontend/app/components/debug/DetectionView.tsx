'use client';

import { useEffect, useState, useMemo, useCallback } from 'react';
import StepFilter, { useStepFilter, STEP_NAMES } from './StepFilter';

interface DetectionEvent {
  id: string;
  ts: number;
  step: string;
  detection_stage: 'regex' | 'ner' | 'llm' | 'unknown';
  detection_type: 'intent' | 'entity' | 'confirmation' | 'other';
  field_name: string;
  raw_input: string;
  extracted_value: string;
  confidence?: number;
  patterns_checked?: string[];
  patterns_matched?: string[];
  alternatives?: string[];
  error?: string;
}

interface DetectionViewProps {
  threadId: string | null;
  pollMs?: number;
}

interface RawTraceEvent {
  ts?: number;
  kind?: string;
  step?: string;
  owner_step?: string;
  subject?: string;
  summary?: string;
  data?: Record<string, unknown>;
  payload?: Record<string, unknown>;
  entity_context?: Record<string, unknown>;
  row_id?: string;
}

function extractStepNumber(step: string): number | null {
  const match = step.match(/step[_\s]?(\d+)/i);
  return match ? parseInt(match[1], 10) : null;
}

function formatStepName(step: string): string {
  const num = extractStepNumber(step);
  if (num !== null) {
    const name = STEP_NAMES[num];
    return name ? `Step ${num}: ${name}` : `Step ${num}`;
  }
  return step || '-';
}

const STAGE_COLORS = {
  regex: { bg: 'bg-blue-500/20', text: 'text-blue-400', label: 'Regex' },
  ner: { bg: 'bg-purple-500/20', text: 'text-purple-400', label: 'NER' },
  llm: { bg: 'bg-green-500/20', text: 'text-green-400', label: 'LLM' },
  unknown: { bg: 'bg-slate-500/20', text: 'text-slate-400', label: '?' },
};

const TYPE_COLORS = {
  intent: { bg: 'bg-orange-500/20', text: 'text-orange-400' },
  entity: { bg: 'bg-cyan-500/20', text: 'text-cyan-400' },
  confirmation: { bg: 'bg-yellow-500/20', text: 'text-yellow-400' },
  other: { bg: 'bg-slate-500/20', text: 'text-slate-400' },
};

export default function DetectionView({ threadId, pollMs = 2000 }: DetectionViewProps) {
  const [events, setEvents] = useState<DetectionEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [viewMode, setViewMode] = useState<'timeline' | 'summary'>('timeline');
  const { selectedStep } = useStepFilter();

  // Filter events by selected step
  const filteredEvents = useMemo(() => {
    if (selectedStep === null) return events;
    return events.filter((event) => {
      const stepNum = extractStepNumber(event.step);
      return stepNum === selectedStep;
    });
  }, [events, selectedStep]);

  // Get available steps
  const availableSteps = useMemo(() => {
    const steps = new Set<number>();
    events.forEach((event) => {
      const stepNum = extractStepNumber(event.step);
      if (stepNum !== null) steps.add(stepNum);
    });
    return Array.from(steps).sort((a, b) => a - b);
  }, [events]);

  // Group events by field for summary view
  const summaryByField = useMemo(() => {
    const grouped = new Map<string, DetectionEvent[]>();
    filteredEvents.forEach((event) => {
      const key = event.field_name || 'unknown';
      if (!grouped.has(key)) grouped.set(key, []);
      grouped.get(key)!.push(event);
    });
    return grouped;
  }, [filteredEvents]);

  // Stats
  const stats = useMemo(() => {
    const byStage = { regex: 0, ner: 0, llm: 0, unknown: 0 };
    const byType = { intent: 0, entity: 0, confirmation: 0, other: 0 };
    filteredEvents.forEach((e) => {
      byStage[e.detection_stage]++;
      byType[e.detection_type]++;
    });
    return { byStage, byType };
  }, [filteredEvents]);

  useEffect(() => {
    if (!threadId) {
      setEvents([]);
      return;
    }

    const controller = new AbortController();
    const fetchData = async () => {
      setLoading(true);
      try {
        const response = await fetch(
          `/api/debug/threads/${encodeURIComponent(threadId)}?granularity=verbose`,
          { signal: controller.signal }
        );
        if (!response.ok) {
          throw new Error(await response.text());
        }
        const payload = await response.json();
        const trace = payload.trace || [];
        const detections = extractDetections(trace);
        setEvents(detections);
        setError(null);
      } catch (err) {
        if ((err as Error).name === 'AbortError') return;
        setError(err instanceof Error ? err.message : 'Failed to load');
      } finally {
        setLoading(false);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, pollMs);
    return () => {
      clearInterval(interval);
      controller.abort();
    };
  }, [threadId, pollMs]);

  const toggleExpanded = useCallback((id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }, []);

  if (!threadId) {
    return (
      <div className="p-8 text-center text-slate-400">
        No thread connected. Go back to the dashboard to connect.
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 bg-red-500/10 border border-red-500/30 text-red-400 rounded-lg">
        {error}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <StepFilter availableSteps={availableSteps} />

      {/* Stats Bar */}
      <div className="flex items-center gap-6 flex-wrap">
        <div className="flex items-center gap-2.5">
          <span className="text-sm text-slate-500 font-medium">Stage:</span>
          {Object.entries(stats.byStage).map(([stage, count]) => count > 0 && (
            <span
              key={stage}
              className={`
                text-sm px-2.5 py-1 rounded-lg font-medium
                ${STAGE_COLORS[stage as keyof typeof STAGE_COLORS].bg.replace('/20', '/30')}
                ${STAGE_COLORS[stage as keyof typeof STAGE_COLORS].text}
              `}
            >
              {STAGE_COLORS[stage as keyof typeof STAGE_COLORS].label}: {count}
            </span>
          ))}
        </div>
        <div className="flex items-center gap-2.5">
          <span className="text-sm text-slate-500 font-medium">Type:</span>
          {Object.entries(stats.byType).map(([type, count]) => count > 0 && (
            <span
              key={type}
              className={`
                text-sm px-2.5 py-1 rounded-lg font-medium capitalize
                ${TYPE_COLORS[type as keyof typeof TYPE_COLORS].bg.replace('/20', '/30')}
                ${TYPE_COLORS[type as keyof typeof TYPE_COLORS].text}
              `}
            >
              {type}: {count}
            </span>
          ))}
        </div>
      </div>

      {/* View Toggle */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <h2 className="text-xl font-semibold text-slate-200 m-0">Detection Pipeline</h2>
        <div className="flex items-center gap-3">
          <span className="text-sm text-slate-400">
            {selectedStep !== null ? `${filteredEvents.length} of ${events.length}` : filteredEvents.length} events
          </span>
          <div className="flex bg-slate-900 rounded-lg overflow-hidden border border-slate-700">
            <button
              type="button"
              onClick={() => setViewMode('timeline')}
              className={`
                px-4 py-2 text-sm font-medium transition-colors
                ${viewMode === 'timeline' ? 'bg-slate-700 text-white' : 'bg-transparent text-slate-400 hover:text-slate-300 hover:bg-slate-800'}
              `}
            >
              Timeline
            </button>
            <button
              type="button"
              onClick={() => setViewMode('summary')}
              className={`
                px-4 py-2 text-sm font-medium transition-colors
                ${viewMode === 'summary' ? 'bg-slate-700 text-white' : 'bg-transparent text-slate-400 hover:text-slate-300 hover:bg-slate-800'}
              `}
            >
              By Field
            </button>
          </div>
        </div>
      </div>

      {events.length === 0 && !loading ? (
        <div className="p-12 text-center text-slate-400 text-sm">
          No detection events recorded yet.
        </div>
      ) : filteredEvents.length === 0 && selectedStep !== null ? (
        <div className="p-12 text-center text-slate-400 text-sm bg-slate-800/20 border border-dashed border-slate-700 rounded-xl">
          No detection events found for Step {selectedStep}: {STEP_NAMES[selectedStep]}.
        </div>
      ) : viewMode === 'summary' ? (
        /* Summary View - Grouped by Field */
        <div className="space-y-4">
          {Array.from(summaryByField.entries()).map(([field, fieldEvents]) => (
            <div key={field} className="bg-slate-800/50 border border-slate-700 rounded-lg p-4">
              <div className="flex items-center justify-between mb-3">
                <span className="font-medium text-slate-200">{field}</span>
                <span className="text-xs text-slate-500">{fieldEvents.length} detection(s)</span>
              </div>
              <div className="space-y-2">
                {fieldEvents.map((event) => (
                  <div key={event.id} className="grid grid-cols-[80px_60px_1fr_60px] gap-4 text-sm items-center">
                    <span className="text-xs text-slate-500 font-mono">{formatTime(event.ts)}</span>
                    <span className={`text-xs px-1.5 py-0.5 rounded text-center ${STAGE_COLORS[event.detection_stage].bg} ${STAGE_COLORS[event.detection_stage].text}`}>
                      {STAGE_COLORS[event.detection_stage].label}
                    </span>
                    <span className="text-slate-300 truncate">{event.extracted_value || '(none)'}</span>
                    {event.confidence !== undefined && (
                      <span className={`text-xs text-right ${event.confidence > 0.7 ? 'text-green-400' : event.confidence > 0.4 ? 'text-yellow-400' : 'text-red-400'}`}>
                        {(event.confidence * 100).toFixed(0)}%
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : (
        /* Timeline View */
        <div className="space-y-0">
          {/* Header */}
          <div className="grid grid-cols-[80px_100px_80px_100px_1fr_120px_40px] gap-4 px-4 py-2 text-xs font-semibold text-slate-500 uppercase tracking-wider border-b border-slate-700/50">
            <div>Time</div>
            <div>Step</div>
            <div>Stage</div>
            <div>Type</div>
            <div>Field</div>
            <div>Value</div>
            <div></div>
          </div>
          
          {filteredEvents.map((event) => {
            const stepNum = extractStepNumber(event.step);
            const isExpanded = expandedIds.has(event.id);
            const stageColor = STAGE_COLORS[event.detection_stage];
            const typeColor = TYPE_COLORS[event.detection_type];

            return (
              <div
                key={event.id}
                id={stepNum !== null ? `step-${stepNum}` : undefined}
                className="bg-slate-800/30 border-b border-slate-700/50 hover:bg-slate-800/60 transition-colors"
              >
                <div
                  onClick={() => toggleExpanded(event.id)}
                  className="grid grid-cols-[80px_100px_80px_100px_1fr_120px_40px] gap-4 px-4 py-3 items-center cursor-pointer"
                >
                  <span className="text-xs text-slate-500 font-mono">
                    {formatTime(event.ts)}
                  </span>
                  
                  <div>
                    <span className="text-xs px-2 py-0.5 rounded bg-slate-700/50 text-slate-300 border border-slate-600/30 whitespace-nowrap">
                      {formatStepName(event.step)}
                    </span>
                  </div>

                  <div>
                    <span className={`text-xs px-2 py-0.5 rounded border ${stageColor.bg} ${stageColor.text} border-opacity-20`}>
                      {stageColor.label}
                    </span>
                  </div>

                  <div>
                    <span className={`text-xs px-2 py-0.5 rounded border ${typeColor.bg} ${typeColor.text} border-opacity-20 capitalize`}>
                      {event.detection_type}
                    </span>
                  </div>

                  <span className="text-sm font-medium text-slate-400 truncate" title={event.field_name}>
                    {event.field_name}
                  </span>

                  <span className="text-sm text-slate-200 truncate font-mono" title={event.extracted_value}>
                    {event.extracted_value || '(none)'}
                  </span>

                  <span className="text-slate-500 text-xs text-right">
                    {isExpanded ? 'Hide' : 'Show'}
                  </span>
                </div>

                {isExpanded && (
                  <div className="px-4 pb-4 pt-2 bg-slate-900/30 border-t border-slate-700/50 space-y-4 ml-[80px]">
                    <div className="grid grid-cols-2 gap-8">
                      {/* Left Col */}
                      <div className="space-y-4">
                        {/* Input that triggered detection */}
                        {event.raw_input && (
                          <div>
                            <div className="text-xs text-slate-500 uppercase tracking-wider mb-1.5">
                              Input Text
                            </div>
                            <div className="text-sm text-slate-300 bg-slate-950 p-3 rounded-md font-mono whitespace-pre-wrap max-h-32 overflow-auto border border-slate-800">
                              {event.raw_input}
                            </div>
                          </div>
                        )}

                        {/* Extracted value */}
                        <div>
                          <div className="text-xs text-slate-500 uppercase tracking-wider mb-1.5">
                            Extracted Value
                          </div>
                          <div className="text-sm font-medium text-blue-400 bg-slate-950 p-2 rounded border border-slate-800 font-mono">
                            {event.extracted_value || '(none)'}
                          </div>
                        </div>
                      </div>

                      {/* Right Col */}
                      <div className="space-y-4">
                         {/* Confidence */}
                         {event.confidence !== undefined && (
                          <div>
                            <div className="text-xs text-slate-500 uppercase tracking-wider mb-1.5">
                              Confidence
                            </div>
                            <span className={`text-xs px-2 py-1 rounded font-medium ${
                              event.confidence > 0.7 ? 'bg-green-500/20 text-green-400' :
                              event.confidence > 0.4 ? 'bg-yellow-500/20 text-yellow-400' :
                              'bg-red-500/20 text-red-400'
                            }`}>
                              {(event.confidence * 100).toFixed(1)}%
                            </span>
                          </div>
                        )}

                        {/* Patterns checked (for regex stage) */}
                        {event.patterns_matched && event.patterns_matched.length > 0 && (
                          <div>
                            <div className="text-xs text-slate-500 uppercase tracking-wider mb-1.5">
                              Patterns Matched
                            </div>
                            <div className="flex flex-wrap gap-2">
                              {event.patterns_matched.map((p, i) => (
                                <span key={i} className="text-xs px-2 py-1 rounded bg-green-500/10 text-green-400 border border-green-500/20 font-mono">
                                  {p}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* Alternatives */}
                        {event.alternatives && event.alternatives.length > 0 && (
                          <div>
                            <div className="text-xs text-slate-500 uppercase tracking-wider mb-1.5">
                              Alternatives Considered
                            </div>
                            <div className="flex flex-wrap gap-2">
                              {event.alternatives.map((alt, i) => (
                                <span key={i} className="text-xs px-2 py-1 rounded bg-slate-800 text-slate-400 border border-slate-700">
                                  {alt}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* Error if any */}
                        {event.error && (
                          <div className="text-xs text-red-400 bg-red-500/10 p-3 rounded border border-red-500/20">
                            Error: {event.error}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Legend */}
      <div className="bg-slate-800/30 border border-slate-700 rounded-xl p-5">
        <div className="font-semibold text-slate-300 mb-3 text-sm">Detection Pipeline Stages</div>
        <div className="flex flex-wrap gap-6 text-sm text-slate-400">
          <div><span className="text-blue-400 font-medium">Regex</span> - Pattern matching (fastest, first checked)</div>
          <div><span className="text-purple-400 font-medium">NER</span> - Named Entity Recognition</div>
          <div><span className="text-green-400 font-medium">LLM</span> - AI extraction (slowest, most flexible)</div>
        </div>
      </div>
    </div>
  );
}

function extractDetections(trace: RawTraceEvent[]): DetectionEvent[] {
  const detections: DetectionEvent[] = [];

  trace.forEach((event, index) => {
    const kind = event.kind || '';
    const data = event.data || event.payload || {};
    const id = event.row_id || `${event.ts}-${index}`;

    // Entity captures (from extraction pipeline)
    if (kind === 'ENTITY_CAPTURE' || kind === 'ENTITY_SUPERSEDED') {
      const entityCtx = event.entity_context || {};
      const parserUsed = (data.parser_used as string) || '';

      detections.push({
        id,
        ts: event.ts || 0,
        step: event.step || event.owner_step || '',
        detection_stage: parserUsed.includes('regex') ? 'regex' :
                        parserUsed.includes('ner') ? 'ner' :
                        parserUsed.includes('llm') ? 'llm' : 'unknown',
        detection_type: 'entity',
        field_name: (entityCtx.key as string) || event.subject || 'unknown',
        raw_input: (data.source_text as string) || (data.raw_input as string) || '',
        extracted_value: String(entityCtx.value || ''),
        patterns_matched: parserUsed ? [parserUsed] : [],
      });
    }

    // Intent classification
    if (kind.includes('INTENT') || kind.includes('CLASSIFY')) {
      detections.push({
        id,
        ts: event.ts || 0,
        step: event.step || event.owner_step || '',
        detection_stage: 'llm',
        detection_type: 'intent',
        field_name: 'intent',
        raw_input: (data.message as string) || (data.raw_input as string) || '',
        extracted_value: (data.intent as string) || (data.result as string) || event.subject || '',
        confidence: data.confidence as number | undefined,
        alternatives: data.alternatives as string[] | undefined,
        patterns_matched: data.matched_patterns as string[] | undefined,
      });
    }

    // LLM extraction responses (agent extractor)
    if (kind === 'AGENT_PROMPT_OUT') {
      const outputs = data.outputs as Record<string, unknown> | undefined;
      if (outputs) {
        // Check if it's an intent classification
        if (outputs.intent !== undefined) {
          detections.push({
            id: `${id}-intent`,
            ts: event.ts || 0,
            step: event.step || event.owner_step || '',
            detection_stage: 'llm',
            detection_type: 'intent',
            field_name: 'intent',
            raw_input: (data.prompt_text as string) || '',
            extracted_value: String(outputs.intent || ''),
            confidence: outputs.confidence as number | undefined,
          });
        }

        // Extract individual entity extractions from outputs
        const entityFields = ['date', 'email', 'participants', 'phone', 'event_date',
          'start_time', 'end_time', 'room', 'layout', 'name', 'company', 'city'];

        entityFields.forEach((field) => {
          if (outputs[field] !== null && outputs[field] !== undefined) {
            detections.push({
              id: `${id}-${field}`,
              ts: event.ts || 0,
              step: event.step || event.owner_step || '',
              detection_stage: 'llm',
              detection_type: 'entity',
              field_name: field,
              raw_input: (data.prompt_text as string) || '',
              extracted_value: String(outputs[field]),
            });
          }
        });
      }
    }
  });

  return detections.reverse();
}

function formatTime(ts: number): string {
  if (!ts) return '--:--:--';
  try {
    const date = new Date(ts * 1000);
    return date.toLocaleTimeString('en-GB', { hour12: false });
  } catch {
    return '--:--:--';
  }
}
