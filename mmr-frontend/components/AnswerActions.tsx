"use client";

import { useState } from "react";
import { Copy, Download, RotateCcw, Square } from "lucide-react";
import { RetrievedChunk } from "@/types/rag";

interface AnswerActionsProps {
  answer: string;
  messageId: string;
  sources: RetrievedChunk[];
  onRegenerate?: () => void;
  onStop?: () => void;
  isGenerating?: boolean;
  isStopping?: boolean;
}

export function answerExportMarkdown(answer: string, sources: RetrievedChunk[]): string {
  if (!sources.length) return `${answer}\n`;
  const sourceLines = sources.map((source) => {
    const location = source.page_numbers?.length ? `pages ${source.page_numbers.join(", ")}` : "page unavailable";
    return `- ${source.filename || "Document"} (${location}; source ${source.chunk_id})`;
  });
  return `${answer}\n\n## Sources\n${sourceLines.join("\n")}\n`;
}

export function AnswerActions({ answer, messageId, sources, onRegenerate, onStop, isGenerating = false, isStopping = false }: AnswerActionsProps) {
  const [actionStatus, setActionStatus] = useState("");

  const copyAnswer = async () => {
    try {
      await navigator.clipboard.writeText(answer);
      setActionStatus("Answer copied");
    } catch {
      setActionStatus("Could not copy answer");
    }
  };

  const exportAnswer = () => {
    const blob = new Blob([answerExportMarkdown(answer, sources)], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `answer-${messageId.replace(/[^a-zA-Z0-9_-]/g, "_")}.md`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
    setActionStatus("Answer exported");
  };

  return (
    <div className="flex flex-wrap items-center gap-2 text-[11px] text-neutral-500" aria-label="Answer actions">
      {answer && <>
        <button type="button" onClick={() => void copyAnswer()} className="inline-flex items-center gap-1 hover:text-[#D4AF37]"><Copy size={13} /> Copy</button>
        <button type="button" onClick={exportAnswer} className="inline-flex items-center gap-1 hover:text-[#D4AF37]"><Download size={13} /> Export</button>
      </>}
      {onRegenerate && !isGenerating && <button type="button" onClick={onRegenerate} className="inline-flex items-center gap-1 hover:text-[#D4AF37]"><RotateCcw size={13} /> Regenerate</button>}
      {isGenerating && onStop && <button type="button" onClick={onStop} disabled={isStopping} className="inline-flex items-center gap-1 text-red-500 disabled:opacity-50"><Square size={13} /> {isStopping ? "Stopping..." : "Stop generating"}</button>}
      {actionStatus && <span role="status">{actionStatus}</span>}
    </div>
  );
}
