"use client";

import React from "react";
import { RetrievedChunk } from "@/types/rag";

export function SourceCitationCard({ chunk }: { chunk: RetrievedChunk }) {
  const content = chunk.metadata?.original_content || {
    raw_text: "",
    tables_html: [],
    images_base64: [],
  };

  return (
    <div className="border border-slate-200 dark:border-slate-800 rounded-lg p-4 bg-slate-50 dark:bg-slate-900 space-y-3">
      <div className="flex items-center justify-between text-xs font-semibold text-slate-500">
        <span>Chunk #{chunk.chunk_id}</span>
      </div>

      {/* Raw Text */}
      {content.raw_text && (
        <p className="text-sm text-slate-700 dark:text-slate-300 leading-relaxed">
          {content.raw_text}
        </p>
      )}

      {/* Rendered HTML Tables */}
      {content.tables_html && content.tables_html.length > 0 && (
        <div className="space-y-2">
          <span className="text-xs font-medium text-slate-500">Extracted Table:</span>
          {content.tables_html.map((tableHtml, idx) => (
            <div
              key={idx}
              className="overflow-x-auto text-xs border border-slate-300 rounded p-2 bg-white dark:bg-slate-950"
              dangerouslySetInnerHTML={{ __html: tableHtml }}
            />
          ))}
        </div>
      )}

      {/* Base64 Images */}
      {content.images_base64 && content.images_base64.length > 0 && (
        <div className="space-y-2">
          <span className="text-xs font-medium text-slate-500">Extracted Visual Content:</span>
          <div className="grid grid-cols-1 gap-2">
            {content.images_base64.map((imgBase64, idx) => (
              <div key={idx} className="border rounded p-1 bg-white max-w-md mx-auto">
                <img
                  src={`data:image/jpeg;base64,${imgBase64}`}
                  alt={`Chunk visual element ${idx + 1}`}
                  className="w-full h-auto object-contain rounded"
                />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}