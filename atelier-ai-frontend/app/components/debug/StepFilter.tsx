'use client';

import { useSearchParams, useRouter, usePathname } from 'next/navigation';
import { useCallback, useEffect } from 'react';

const STEPS = [1, 2, 3, 4, 5, 6, 7];
export const STEP_NAMES: Record<number, string> = {
  1: 'Intake',
  2: 'Date',
  3: 'Room',
  4: 'Offer',
  5: 'Negotiation',
  6: 'Transition',
  7: 'Confirmation',
};

interface StepFilterProps {
  currentStep?: number | null;
  onStepChange?: (step: number | null) => void;
  availableSteps?: number[];
}

export function useStepFilter() {
  const searchParams = useSearchParams();
  const stepParam = searchParams.get('step');
  const selectedStep = stepParam ? parseInt(stepParam, 10) : null;
  return { selectedStep: Number.isNaN(selectedStep) ? null : selectedStep };
}

export default function StepFilter({ currentStep, onStepChange, availableSteps }: StepFilterProps) {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const stepParam = searchParams.get('step');
  const selectedStep = stepParam ? parseInt(stepParam, 10) : null;
  const effectiveStep = Number.isNaN(selectedStep) ? null : selectedStep;

  const handleStepClick = useCallback(
    (step: number | null) => {
      const params = new URLSearchParams(searchParams.toString());
      if (step === null) {
        params.delete('step');
      } else {
        params.set('step', String(step));
      }
      const queryString = params.toString();
      const newUrl = queryString ? `${pathname}?${queryString}` : pathname;
      router.push(newUrl, { scroll: false });

      if (onStepChange) {
        onStepChange(step);
      }

      // Scroll to step anchor if selecting a step
      if (step !== null) {
        setTimeout(() => {
          const anchor = document.getElementById(`step-${step}`);
          if (anchor) {
            anchor.scrollIntoView({ behavior: 'smooth', block: 'start' });
          }
        }, 100);
      }
    },
    [searchParams, router, pathname, onStepChange]
  );

  // On mount, scroll to step if in URL
  useEffect(() => {
    if (effectiveStep !== null) {
      const anchor = document.getElementById(`step-${effectiveStep}`);
      if (anchor) {
        anchor.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }
  }, []);

  return (
    <div className="bg-slate-800/50 border border-slate-700 rounded-xl p-4">
      <div className="flex items-center gap-4 flex-wrap">
        <span className="text-sm text-slate-400 font-medium">Filter by Step:</span>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => handleStepClick(null)}
            className={`
              px-3.5 py-2 rounded-lg text-sm font-medium transition-all duration-200
              ${effectiveStep === null 
                ? 'bg-slate-700 text-white' 
                : 'bg-slate-900 text-slate-400 hover:bg-slate-800 hover:text-slate-300'}
            `}
          >
            All
          </button>
          {STEPS.map((step) => {
            const isAvailable = !availableSteps || availableSteps.includes(step);
            const isSelected = effectiveStep === step;
            const isCurrent = currentStep === step;

            return (
              <button
                key={step}
                type="button"
                onClick={() => handleStepClick(step)}
                title={`${STEP_NAMES[step]}${isCurrent ? ' (current)' : ''}${!isAvailable ? ' (no events)' : ''}`}
                className={`
                  relative px-3.5 py-2 rounded-lg text-sm font-medium transition-all duration-200
                  ${isSelected
                    ? 'bg-blue-600 text-white shadow-lg shadow-blue-500/20'
                    : isCurrent
                      ? 'bg-slate-700 text-blue-400 ring-2 ring-blue-500/30'
                      : !isAvailable
                        ? 'bg-slate-900/50 text-slate-600 hover:bg-slate-800 hover:text-slate-500'
                        : 'bg-slate-900 text-slate-400 hover:bg-slate-800 hover:text-slate-300'}
                `}
              >
                {step}
                {isCurrent && !isSelected && (
                  <span className="absolute -top-1 -right-1 w-2.5 h-2.5 bg-blue-500 rounded-full border-2 border-slate-900" />
                )}
              </button>
            );
          })}
        </div>
        {effectiveStep !== null && (
          <span className="text-sm text-slate-500 ml-2 animate-in fade-in duration-300">
            Step {effectiveStep}: {STEP_NAMES[effectiveStep]}
          </span>
        )}
      </div>
    </div>
  );
}
