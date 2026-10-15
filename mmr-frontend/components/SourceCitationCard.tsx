"use client";

import React from "react";
import Image from "next/image";
import { RetrievedChunk } from "@/types/rag";
import { LightboxData } from "@/components/CitationLightbox";
import { Maximize2, Table as TableIcon, Image as ImageIcon } from "lucide-react";

interface SourceCitationCardProps {
  chunk: RetrievedChunk;
  onOpenLightbox?: (data: LightboxData) => void;
}

export function SourceCitationCard({ chunk, onOpenLightbox }: SourceCitationCardProps) {
  const content = chunk.metadata?.original_content || {
    raw_text: "",
    tables_html: [],
    images_base64: [],
  };

  return (
    <div className="border border-neutral-800 rounded-xl p-4 bg-[#111111] hover:border-neutral-700 transition-all space-y-3">
      
      {/* Header */}
      <div className="flex items-center justify-between text-xs text-neutral-400 font-mono border-b border-neutral-800 pb-2">
        <span className="text-[#D4AF37] font-semibold">Chunk #{chunk.chunk_id}</span>
        <span className="text-[10px] text-neutral-500">Similarity Score Ranked</span>
      </div>

      {/* Text Content */}
      {content.raw_text && (
        <p className="text-xs text-neutral-300 leading-relaxed font-sans line-clamp-4">
          {content.raw_text}
        </p>
      )}

      {/* HTML Tables Section */}
      {content.tables_html && content.tables_html.length > 0 && (
        <div className="space-y-2 pt-1">
          <div className="flex items-center gap-1.5 text-[11px] font-medium text-neutral-400">
            <TableIcon size={13} className="text-[#D4AF37]" />
            <span>Extracted Tables ({content.tables_html.length})</span>
          </div>

          <div className="grid gap-2">
            {content.tables_html.map((tableHtml, idx) => (
              <div
                key={idx}
                onClick={() =>
                  onOpenLightbox &&
                  onOpenLightbox({
                    type: "table",
                    content: tableHtml,
                    chunkId: chunk.chunk_id,
                  })
                }
                className="group relative cursor-pointer overflow-hidden rounded-lg border border-neutral-800 bg-neutral-950 p-2.5 hover:border-[#D4AF37]/50 transition-all"
              >
                <div
                  className="max-h-24 overflow-hidden text-[10px] opacity-75 group-hover:opacity-100 transition-opacity [&_table]:w-full [&_td]:p-1 [&_td]:border [&_td]:border-neutral-800"
                  dangerouslySetInnerHTML={{ __html: tableHtml }}
                />
                <div className="absolute inset-0 bg-gradient-to-t from-neutral-950/90 via-transparent to-transparent flex items-end justify-end p-2 opacity-0 group-hover:opacity-100 transition-opacity">
                  <span className="inline-flex items-center gap-1 text-[10px] text-[#D4AF37] bg-neutral-900 border border-neutral-700 px-2 py-0.5 rounded">
                    <Maximize2 size={10} /> Expand Table
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Base64 Images Section */}
      {content.images_base64 && content.images_base64.length > 0 && (
        <div className="space-y-2 pt-1">
          <div className="flex items-center gap-1.5 text-[11px] font-medium text-neutral-400">
            <ImageIcon size={13} className="text-[#D4AF37]" />
            <span>Extracted Visual Figures ({content.images_base64.length})</span>
          </div>

          <div className="grid grid-cols-2 gap-2">
            {content.images_base64.map((imgBase64, idx) => (
              <div
                key={idx}
                onClick={() =>
                  onOpenLightbox &&
                  onOpenLightbox({
                    type: "image",
                    content: imgBase64,
                    chunkId: chunk.chunk_id,
                  })
                }
                className="group relative cursor-pointer overflow-hidden rounded-lg border border-neutral-800 bg-neutral-950 p-1 hover:border-[#D4AF37]/50 transition-all flex items-center justify-center max-h-32"
              >
                <Image
                  src={`data:image/jpeg;base64,${imgBase64}`}
                  alt={`Extracted element ${idx + 1}`}
                  width={640}
                  height={480}
                  unoptimized
                  className="max-h-28 w-auto object-contain rounded"
                />
                <div className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                  <span className="inline-flex items-center gap-1 text-[10px] text-white bg-[#D4AF37] text-black px-2.5 py-1 rounded-full font-semibold">
                    <Maximize2 size={10} /> Preview
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

    </div>
  );
}
