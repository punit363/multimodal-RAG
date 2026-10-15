"use client";

import React from "react";
import { FileText, CheckSquare, Square, Trash2 } from "lucide-react";

export interface DocumentInfo {
  filename: string;
  chunk_count: number;
}

interface DocumentSelectorProps {
  documents: DocumentInfo[];
  selectedDocNames: string[];
  onToggleDoc: (filename: string) => void;
  onSelectAll: () => void;
  onDeselectAll: () => void;
  onDeleteDoc: (filename: string) => void;
}

export const DocumentSelector: React.FC<DocumentSelectorProps> = ({
  documents,
  selectedDocNames,
  onToggleDoc,
  onSelectAll,
  onDeselectAll,
  onDeleteDoc,
}) => {
  const allSelected = documents.length > 0 && selectedDocNames.length === documents.length;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between text-xs border-b border-neutral-200 dark:border-neutral-800 pb-2">
        <span className="font-semibold text-neutral-700 dark:text-neutral-300">
          Knowledge Base ({documents.length})
        </span>
        <button
          onClick={allSelected ? onDeselectAll : onSelectAll}
          className="text-[11px] text-[#D4AF37] hover:underline font-medium cursor-pointer"
        >
          {allSelected ? "Deselect All" : "Select All"}
        </button>
      </div>

      {documents.length === 0 ? (
        <p className="text-xs text-neutral-500 italic">No indexed documents found.</p>
      ) : (
        <div className="space-y-1.5 max-h-48 overflow-y-auto pr-1">
          {documents.map((doc) => {
            const isSelected = selectedDocNames.includes(doc.filename);
            return (
              <div
                key={doc.filename}
                className={`flex items-center justify-between p-2 rounded-lg border text-xs transition-colors ${
                  isSelected
                    ? "bg-amber-500/10 border-[#D4AF37]/40 text-neutral-900 dark:text-neutral-100"
                    : "bg-neutral-100 dark:bg-neutral-900 border-neutral-200 dark:border-neutral-800 text-neutral-500 opacity-70"
                }`}
              >
                <div
                  onClick={() => onToggleDoc(doc.filename)}
                  className="flex items-center gap-2 cursor-pointer flex-1 min-w-0"
                >
                  {isSelected ? (
                    <CheckSquare size={14} className="text-[#D4AF37] shrink-0" />
                  ) : (
                    <Square size={14} className="text-neutral-400 shrink-0" />
                  )}
                  <FileText size={14} className="text-[#D4AF37] shrink-0" />
                  <span className="truncate font-medium">{doc.filename}</span>
                </div>

                <div className="flex items-center gap-2 shrink-0 ml-2">
                  <span className="text-[10px] font-mono text-neutral-500 bg-neutral-200 dark:bg-neutral-800 px-1.5 py-0.5 rounded">
                    {doc.chunk_count} chunks
                  </span>
                  <button
                    onClick={() => onDeleteDoc(doc.filename)}
                    className="text-neutral-400 hover:text-red-500 transition-colors p-1"
                    title="Delete document"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
