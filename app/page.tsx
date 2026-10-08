"use client";

import { useState } from "react";
import { SourceCitationCard } from "@/components/SourceCitationCard";
import { RetrievedChunk, QueryResponse, IngestResponse } from "@/types/rag";

const API_BASE_URL = "http://localhost:8000";

export default function Home() {
  // Upload State
  const [file, setFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState<string>("");

  // Query State
  const [query, setQuery] = useState("");
  const [isSearching, setIsSearching] = useState(false);
  const [answer, setAnswer] = useState("");
  const [sources, setSources] = useState<RetrievedChunk[]>([]);

  // Handle PDF Upload
  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;

    setIsUploading(true);
    setUploadMessage("Processing PDF with Unstructured...");

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch(`${API_BASE_URL}/api/ingest`, {
        method: "POST",
        body: formData,
      });

      if (!res.ok) throw new Error("Upload failed");

      const data: IngestResponse = await res.json();
      setUploadMessage(`Success: ${data.message}`);
    } catch (err: any) {
      setUploadMessage(`Error: ${err.message || "Failed to process document"}`);
    } finally {
      setIsUploading(false);
    }
  };

  // Handle RAG Search
  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;

    setIsSearching(true);
    setAnswer("");
    setSources([]);

    try {
      const res = await fetch(`${API_BASE_URL}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, top_k: 3 }),
      });

      if (!res.ok) throw new Error("Query execution failed");

      const data: QueryResponse = await res.json();
      setAnswer(data.answer);
      setSources(data.sources);
    } catch (err: any) {
      setAnswer(`Error: ${err.message || "Something went wrong"}`);
    } finally {
      setIsSearching(false);
    }
  };

  return (
    <main className="min-h-screen bg-slate-100 dark:bg-slate-950 p-6 md:p-12 text-slate-900 dark:text-slate-100">
      <div className="max-w-4xl mx-auto space-y-8">
        
        {/* Header */}
        <header className="border-b pb-4 border-slate-300 dark:border-slate-800">
          <h1 className="text-3xl font-bold tracking-tight">Multi-Modal RAG Explorer</h1>
          <p className="text-sm text-slate-500 mt-1">
            Upload complex PDFs containing text, tables, and images, then ask structured questions.
          </p>
        </header>

        {/* Ingestion Section */}
        <section className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg p-6 shadow-sm space-y-4">
          <h2 className="text-lg font-semibold">1. Document Ingestion</h2>
          <form onSubmit={handleUpload} className="flex flex-col sm:flex-row gap-3">
            <input
              type="file"
              accept=".pdf"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              className="flex-1 text-sm file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100 dark:file:bg-slate-800 dark:file:text-slate-200"
            />
            <button
              type="submit"
              disabled={!file || isUploading}
              className="px-5 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-md text-sm font-medium disabled:opacity-50 transition-colors"
            >
              {isUploading ? "Ingesting..." : "Process PDF"}
            </button>
          </form>
          {uploadMessage && (
            <p className="text-xs font-mono text-slate-600 dark:text-slate-400">
              {uploadMessage}
            </p>
          )}
        </section>

        {/* Search Section */}
        <section className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg p-6 shadow-sm space-y-4">
          <h2 className="text-lg font-semibold">2. Query System</h2>
          <form onSubmit={handleSearch} className="flex gap-3">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="e.g., How many attention heads does the Transformer use?"
              className="flex-1 border border-slate-300 dark:border-slate-700 rounded-md px-4 py-2 text-sm bg-transparent focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <button
              type="submit"
              disabled={isSearching}
              className="px-5 py-2 bg-green-600 hover:bg-green-700 text-white rounded-md text-sm font-medium disabled:opacity-50 transition-colors"
            >
              {isSearching ? "Thinking..." : "Ask"}
            </button>
          </form>
        </section>

        {/* Answer Output */}
        {answer && (
          <section className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg p-6 shadow-sm space-y-3">
            <h3 className="text-md font-semibold text-blue-600 dark:text-blue-400">Generated Answer</h3>
            <p className="text-sm leading-relaxed whitespace-pre-wrap">{answer}</p>
          </section>
        )}

        {/* Retained Sources Output */}
        {sources.length > 0 && (
          <section className="space-y-4">
            <h3 className="text-md font-semibold text-slate-700 dark:text-slate-300">
              Retrieved Sources ({sources.length})
            </h3>
            <div className="grid gap-4">
              {sources.map((chunk) => (
                <SourceCitationCard key={chunk.chunk_id} chunk={chunk} />
              ))}
            </div>
          </section>
        )}

      </div>
    </main>
  );
}