// components/IngestionStepper.tsx
"use client";

import React from "react";
import { CheckCircle2, Loader2, AlertCircle } from "lucide-react";

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

export function IngestionStepper({ currentStep, errorMsg }: { currentStep: number; errorMsg?: string }) {
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
        <div className="flex items-center gap-2 text-xs text-red-400 mt-2 pt-2 border-t border-neutral-800">
          <AlertCircle size={14} />
          <span>{errorMsg}</span>
        </div>
      )}
    </div>
  );
}