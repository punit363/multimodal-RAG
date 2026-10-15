// components/IngestionStepper.tsx
"use client";

import React from "react";
import { CheckCircle2, Loader2, AlertCircle, RotateCcw, X } from "lucide-react";

export interface StepState {
  step: number;
  label: string;
  status: "idle" | "in_progress" | "completed" | "error";
}

const STEPS = [
  { id: 1, name: "Partitioning PDF Layout" },
  { id: 2, name: "Extracting Tables & Vision Elements" },
  { id: 3, name: "Generating Multi-Modal Summaries" },
  { id: 4, name: "Persisting ChromaDB Embeddings" },
];

interface IngestionStepperProps {
  currentStep: number;
  errorMsg?: string;
  isRunning?: boolean;
  onCancel?: () => void;
  onRetry?: () => void;
}

export function IngestionStepper({
  currentStep,
  errorMsg,
  isRunning,
  onCancel,
  onRetry,
}: IngestionStepperProps) {
  return (
    <div className="space-y-3 p-4 rounded-xl border border-neutral-800 bg-neutral-900/60">
      <div className="text-xs font-mono uppercase tracking-wider text-amber-500 font-semibold">
        Ingestion Pipeline Progress
      </div>
      
      <div className="space-y-2.5">
        {STEPS.map((s) => {
          const isDone = currentStep > s.id || currentStep === 5;
          const isCurrent = currentStep === s.id;

          return (
            <div key={s.id} className="flex items-center gap-3 text-xs">
              {isDone ? (
                <CheckCircle2 size={16} className="text-[#D4AF37]" />
              ) : isCurrent ? (
                <Loader2 size={16} className="text-[#D4AF37] animate-spin" />
              ) : (
                <div className="w-4 h-4 rounded-full border border-neutral-700 bg-neutral-950" />
              )}

              <span
                className={
                  isDone
                    ? "text-neutral-200 font-medium"
                    : isCurrent
                    ? "text-[#D4AF37] font-semibold"
                    : "text-neutral-500"
                }
              >
                {s.name}
              </span>
            </div>
          );
        })}
      </div>

      {errorMsg && (
        <div className="space-y-2 text-xs text-red-400 mt-2 pt-2 border-t border-neutral-800">
          <div className="flex items-center gap-2">
            <AlertCircle size={14} />
            <span>{errorMsg}</span>
          </div>
          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              className="inline-flex items-center gap-1 rounded border border-red-500/40 px-2 py-1 text-[11px] hover:bg-red-500/10"
            >
              <RotateCcw size={12} /> Retry upload
            </button>
          )}
        </div>
      )}

      {isRunning && onCancel && (
        <button
          type="button"
          onClick={onCancel}
          className="inline-flex items-center gap-1 text-[11px] text-neutral-400 hover:text-red-400"
        >
          <X size={12} /> Cancel ingestion
        </button>
      )}
    </div>
  );
}
