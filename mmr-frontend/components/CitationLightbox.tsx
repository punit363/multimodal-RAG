"use client";

import React, { useEffect } from "react";
import { X, ZoomIn, FileText, Image as ImageIcon, Table as TableIcon } from "lucide-react";

export interface LightboxData {
  type: "image" | "table";
  content: string; // Base64 image string or HTML table string
  chunkId: number;
  title?: string;
}

interface CitationLightboxProps {
  data: LightboxData | null;
  onClose: () => void;
}

export function CitationLightbox({ data, onClose }: CitationLightboxProps) {
  // Close modal on Escape key press
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  if (!data) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-4 sm:p-8 animate-in fade-in duration-200">
      {/* Modal Container */}
      <div className="relative w-full max-w-5xl max-h-[90vh] bg-[#111111] border border-neutral-800 rounded-2xl flex flex-col overflow-hidden shadow-2xl">
        
        {/* Modal Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-neutral-800 bg-[#0D0D0D]">
          <div className="flex items-center gap-3">
            {data.type === "image" ? (
              <ImageIcon size={18} className="text-[#D4AF37]" />
            ) : (
              <TableIcon size={18} className="text-[#D4AF37]" />
            )}
            <div>
              <h3 className="text-sm font-semibold text-neutral-200">
                {data.type === "image" ? "Extracted Visual Element" : "Extracted Table Structure"}
              </h3>
              <p className="text-[11px] text-neutral-500 font-mono">
                Source: Chunk #{data.chunkId}
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-2 rounded-full text-neutral-400 hover:text-white hover:bg-neutral-800 transition-colors cursor-pointer"
            aria-label="Close Preview"
          >
            <X size={18} />
          </button>
        </div>

        {/* Modal Content Body */}
        <div className="flex-1 overflow-auto p-6 flex items-center justify-center bg-[#0A0A0A]">
          {data.type === "image" ? (
            <div className="relative max-w-full max-h-[70vh] flex items-center justify-center overflow-auto rounded-lg border border-neutral-800 bg-neutral-950 p-2">
              <img
                src={`data:image/jpeg;base64,${data.content}`}
                alt={`Extracted figure from chunk ${data.chunkId}`}
                className="max-w-full max-h-[65vh] object-contain rounded"
              />
            </div>
          ) : (
            <div className="w-full overflow-x-auto rounded-xl border border-neutral-800 bg-neutral-950 p-4">
              <div
                className="prose prose-invert max-w-none text-xs [&_table]:w-full [&_table]:border-collapse [&_th]:border [&_th]:border-neutral-700 [&_th]:p-2 [&_th]:bg-neutral-900 [&_th]:text-[#D4AF37] [&_td]:border [&_td]:border-neutral-800 [&_td]:p-2 [&_td]:text-neutral-300"
                dangerouslySetInnerHTML={{ __html: data.content }}
              />
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div className="px-6 py-3 border-t border-neutral-800 bg-[#0D0D0D] flex items-center justify-between text-xs text-neutral-500">
          <div className="flex items-center gap-2">
            <ZoomIn size={14} className="text-[#D4AF37]" />
            <span>Click outside or press <kbd className="px-1.5 py-0.5 rounded bg-neutral-800 border border-neutral-700 font-mono text-[10px]">ESC</kbd> to exit</span>
          </div>
        </div>

      </div>
    </div>
  );
}