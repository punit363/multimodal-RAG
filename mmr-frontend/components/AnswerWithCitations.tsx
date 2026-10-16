import { Fragment } from "react";
import { RetrievedChunk } from "@/types/rag";

interface AnswerWithCitationsProps {
  text: string;
  sources: RetrievedChunk[];
  onOpenPdf: (chunk: RetrievedChunk) => void;
}

export function AnswerWithCitations({ text, sources, onOpenPdf }: AnswerWithCitationsProps) {
  const parts = text.split(/(\[\[source:[^\]]+\]\])/g);
  return (
    <>
      {parts.map((part, index) => {
        const match = /^\[\[source:(.+)\]\]$/.exec(part);
        const source = match && sources.find((chunk) => String(chunk.chunk_id) === match[1]);
        if (!source || !source.document_id) return <Fragment key={index}>{part}</Fragment>;
        const page = source.page_numbers?.[0];
        const label = `${source.filename || "Document"}${page ? `, p.${page}` : ""}`;
        return (
          <button
            key={index}
            type="button"
            onClick={() => onOpenPdf(source)}
            aria-label={`Open citation ${label}`}
            className="mx-1 rounded border border-amber-500/40 px-1 text-[#D4AF37] hover:bg-amber-500/10"
          >
            [{label}]
          </button>
        );
      })}
    </>
  );
}
