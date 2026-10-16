"use client";

import { ThumbsDown, ThumbsUp } from "lucide-react";

export type AnswerRating = "helpful" | "not_helpful" | null;

interface AnswerFeedbackProps {
  feedback: AnswerRating;
  pending?: boolean;
  onChange: (feedback: AnswerRating) => void;
}

export function AnswerFeedback({ feedback, pending = false, onChange }: AnswerFeedbackProps) {
  return (
    <div className="flex items-center gap-2 text-[11px] text-neutral-500" aria-label="Answer feedback">
      <span>Was this answer useful?</span>
      <button type="button" aria-label="Helpful answer" aria-pressed={feedback === "helpful"} disabled={pending}
        onClick={() => onChange(feedback === "helpful" ? null : "helpful")}
        className="rounded p-1 hover:text-emerald-500 aria-pressed:text-emerald-500 disabled:opacity-50"><ThumbsUp size={14} /></button>
      <button type="button" aria-label="Not helpful answer" aria-pressed={feedback === "not_helpful"} disabled={pending}
        onClick={() => onChange(feedback === "not_helpful" ? null : "not_helpful")}
        className="rounded p-1 hover:text-amber-500 aria-pressed:text-amber-500 disabled:opacity-50"><ThumbsDown size={14} /></button>
    </div>
  );
}
