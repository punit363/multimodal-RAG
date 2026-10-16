"use client";

import { useEffect, useRef, useState } from "react";
import { API_BASE_URL } from "@/lib/api";
import { RetrievedChunk } from "@/types/rag";
import type { PDFDocumentLoadingTask, RenderTask } from "pdfjs-dist";

interface PdfCitationViewerProps {
  chunk: RetrievedChunk;
  onClose: () => void;
}

export function PdfCitationViewer({ chunk, onClose }: PdfCitationViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [pageNumber, setPageNumber] = useState(chunk.page_numbers?.[0] || 1);
  const [pageCount, setPageCount] = useState(0);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const documentId = chunk.document_id;
  const rect = chunk.highlight_rect?.page === pageNumber ? chunk.highlight_rect : null;

  useEffect(() => {
    let cancelled = false;
    let loadingTask: PDFDocumentLoadingTask | undefined;
    let renderTask: RenderTask | undefined;

    async function renderPage() {
      if (!documentId || !canvasRef.current) {
        setError("This source has no stored PDF available.");
        setLoading(false);
        return;
      }
      setError("");
      setLoading(true);
      try {
        const pdfjs = await import("pdfjs-dist/legacy/build/pdf.mjs");
        pdfjs.GlobalWorkerOptions.workerSrc = new URL(
          "pdfjs-dist/legacy/build/pdf.worker.min.mjs",
          import.meta.url
        ).toString();
        loadingTask = pdfjs.getDocument({
          url: `${API_BASE_URL}/api/documents/${encodeURIComponent(documentId)}/pdf`,
          isEvalSupported: false,
        });
        const pdf = await loadingTask.promise;
        if (cancelled) return;
        setPageCount(pdf.numPages);
        if (pageNumber > pdf.numPages) {
          setPageNumber(pdf.numPages);
          return;
        }
        const page = await pdf.getPage(pageNumber);
        if (cancelled || !canvasRef.current) return;
        const baseViewport = page.getViewport({ scale: 1 });
        const scale = Math.min(1.6, 760 / baseViewport.width);
        const viewport = page.getViewport({ scale });
        const canvas = canvasRef.current;
        const context = canvas.getContext("2d");
        if (!context) throw new Error("Could not create the PDF canvas.");
        canvas.width = Math.floor(viewport.width);
        canvas.height = Math.floor(viewport.height);
        renderTask = page.render({ canvas, canvasContext: context, viewport });
        await renderTask.promise;
      } catch (cause) {
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : "Could not open the PDF.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void renderPage();
    return () => {
      cancelled = true;
      renderTask?.cancel();
      void loadingTask?.destroy();
    };
  }, [documentId, pageNumber]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`PDF source: ${chunk.filename || "Document"}`}
      className="fixed inset-0 z-50 flex flex-col bg-black/90 p-3 text-white"
    >
      <div className="mx-auto flex w-full max-w-5xl items-center justify-between gap-3 py-2">
        <div>
          <div className="text-sm font-semibold">{chunk.filename || "Document"}</div>
          <div className="text-xs text-neutral-300">
            Page {pageNumber}{pageCount ? ` of ${pageCount}` : ""}
            {rect ? " · cited content highlighted" : " · page-level source"}
          </div>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <button type="button" disabled={pageNumber <= 1} onClick={() => setPageNumber((page) => page - 1)} className="rounded border px-2 py-1 disabled:opacity-40">Previous</button>
          <button type="button" disabled={!pageCount || pageNumber >= pageCount} onClick={() => setPageNumber((page) => page + 1)} className="rounded border px-2 py-1 disabled:opacity-40">Next</button>
          <button type="button" onClick={onClose} className="rounded border px-2 py-1">Close PDF</button>
        </div>
      </div>
      <div className="flex-1 overflow-auto text-center">
        {loading && <p className="py-4 text-sm">Loading PDF page...</p>}
        {error && <p role="alert" className="py-4 text-sm text-red-300">{error}</p>}
        <div className="relative mx-auto inline-block max-w-full">
          <canvas ref={canvasRef} aria-label={`PDF page ${pageNumber}`} className="max-w-full bg-white" />
          {rect && !loading && !error && (
            <div
              aria-label="Cited content highlight"
              className="pointer-events-none absolute border-2 border-amber-400 bg-amber-300/30"
              style={{
                left: `${rect.left * 100}%`,
                top: `${rect.top * 100}%`,
                width: `${rect.width * 100}%`,
                height: `${rect.height * 100}%`,
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}
