"use client";

import React, { useState } from "react";
import Link from "next/link";
import { ThemeToggle } from "@/components/ThemeToggle";
import { IngestionStepper } from "@/components/IngestionStepper";
import { SourceCitationCard } from "@/components/SourceCitationCard";
import { RetrievedChunk, QueryResponse } from "@/types/rag";
import {
  Plus,
  Folder,
  UploadCloud,
  MessageSquare,
  FileText,
  Send,
  Database,
  ArrowLeft
} from "lucide-react";

const API_BASE_URL = "http://localhost:8000";

export default function ChatWorkspace() {
  // Navigation & File Ingestion States
  const [file, setFile] = useState<File | null>(null);
  const [ingestStep, setIngestStep] = useState<number>(0);
  const [ingestError, setIngestError] = useState<string>("");
  const [uploadedSources, setUploadedSources] = useState<string[]>([]);

  // Conversation States
  const [conversations, setConversations] = useState<Array<{ id: number; title: string }>>([]);
  const [activeChat, setActiveChat] = useState<boolean>(false);
  const [query, setQuery] = useState("");
  const [isSearching, setIsSearching] = useState(false);
  const [answer, setAnswer] = useState("");
  const [sources, setSources] = useState<RetrievedChunk[]>([]);

  // Handle PDF Upload with SSE Progress Stepper
  const handleIngestStream = async (selectedFile: File) => {
    setFile(selectedFile);
    setIngestStep(1);
    setIngestError("");

    const formData = new FormData();
    formData.append("file", selectedFile);

    try {
      const response = await fetch(`${API_BASE_URL}/api/ingest-stream`, {
        method: "POST",
        body: formData,
      });

      if (!response.body) throw new Error("No response body from ingestion stream");

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        const textChunk = decoder.decode(value);
        const lines = textChunk.split("\n\n");

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const data = JSON.parse(line.replace("data: ", ""));
            if (data.status === "error") {
              setIngestError(data.label);
              break;
            }
            setIngestStep(data.step);
            if (data.status === "completed") {
              setUploadedSources((prev) => [...prev, data.filename]);
            }
          }
        }
      }
    } catch (err: any) {
      setIngestError(err.message || "Failed to process document.");
    }
  };

  // Handle Search Query
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

  const startNewConversation = () => {
    const newId = conversations.length + 1;
    setConversations((prev) => [...prev, { id: newId, title: `Conversation ${newId}` }]);
    setActiveChat(true);
    setAnswer("");
    setSources([]);
    setQuery("");
  };

  return (
    <div className="flex h-screen w-full bg-[#0D0D0D] text-neutral-100 overflow-hidden font-sans">
      
      {/* LEFT SIDEBAR: Navigation & Projects */}
      <aside className="w-64 border-r border-neutral-800 bg-[#111111] flex flex-col p-4 gap-4 select-none">
        <div className="flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2 font-bold text-sm tracking-wide text-neutral-200 hover:text-[#D4AF37]">
            <ArrowLeft size={16} /> MultiModal.RAG
          </Link>
          <ThemeToggle />
        </div>

        <button
          onClick={startNewConversation}
          className="flex items-center justify-center gap-2 w-full py-2 px-3 rounded-lg border border-neutral-700 bg-neutral-900 hover:bg-neutral-800 text-xs font-semibold text-neutral-200 transition-all cursor-pointer"
        >
          <Plus size={14} /> New project
        </button>

        <div className="space-y-1 text-xs text-neutral-400">
          <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-neutral-900/50 text-neutral-200 font-medium">
            <Folder size={14} className="text-[#D4AF37]" />
            <span>Projects</span>
          </div>
        </div>

        {/* Existing Conversations List */}
        <div className="flex-1 overflow-y-auto space-y-1 pt-2">
          {conversations.map((c) => (
            <div
              key={c.id}
              onClick={() => setActiveChat(true)}
              className="flex items-center gap-2 px-3 py-2 rounded-lg text-xs text-neutral-400 hover:bg-neutral-900 hover:text-neutral-200 cursor-pointer"
            >
              <MessageSquare size={13} />
              <span className="truncate">{c.title}</span>
            </div>
          ))}
        </div>
      </aside>

      {/* CENTER WORKSPACE: Main Chat Area */}
      <main className="flex-1 flex flex-col bg-[#0A0A0A] relative overflow-hidden">
        {/* Workspace Header */}
        <header className="h-14 border-b border-neutral-800 flex items-center justify-between px-6 bg-[#0D0D0D]">
          <div>
            <h1 className="text-sm font-semibold text-neutral-200">GenAI Team Workspace</h1>
            <p className="text-[11px] text-neutral-500">Multi-modal knowledge reasoning</p>
          </div>
          <button
            onClick={startNewConversation}
            className="flex items-center gap-1.5 py-1.5 px-3 rounded-md bg-neutral-100 text-black dark:bg-neutral-100 dark:text-black hover:bg-[#D4AF37] text-xs font-semibold transition-all cursor-pointer"
          >
            <Plus size={14} /> New conversation
          </button>
        </header>

        {/* Workspace Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {!activeChat ? (
            /* Empty State (Matching Reference) */
            <div className="h-full flex flex-col items-center justify-center text-center space-y-4 max-w-md mx-auto">
              <div className="w-12 h-12 rounded-xl border border-neutral-800 bg-neutral-900 flex items-center justify-center text-neutral-500">
                <MessageSquare size={20} />
              </div>
              <div className="space-y-1">
                <h3 className="text-sm font-semibold text-neutral-200">No conversations yet</h3>
                <p className="text-xs text-neutral-500 leading-relaxed">
                  Start your first conversation in this project to analyze documents and get multi-modal insights.
                </p>
              </div>
              <button
                onClick={startNewConversation}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-neutral-100 text-black text-xs font-semibold hover:bg-[#D4AF37] transition-all cursor-pointer shadow-lg"
              >
                <Plus size={14} /> Start first conversation
              </button>
            </div>
          ) : (
            /* Active Chat Session */
            <div className="max-w-3xl mx-auto space-y-6">
              {answer && (
                <div className="border border-neutral-800 rounded-xl p-5 bg-neutral-900/40 space-y-3">
                  <span className="text-[10px] font-mono uppercase tracking-widest text-[#D4AF37]">
                    Generated Answer
                  </span>
                  <p className="text-sm text-neutral-200 leading-relaxed whitespace-pre-wrap">{answer}</p>
                </div>
              )}

              {sources.length > 0 && (
                <div className="space-y-3">
                  <span className="text-xs font-mono uppercase tracking-wider text-neutral-500">
                    Retrieved Sources ({sources.length})
                  </span>
                  <div className="grid gap-3">
                    {sources.map((chunk) => (
                      <SourceCitationCard key={chunk.chunk_id} chunk={chunk} />
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Input Query Bar */}
        {activeChat && (
          <div className="p-4 border-t border-neutral-800 bg-[#0D0D0D]">
            <form onSubmit={handleSearch} className="max-w-3xl mx-auto flex gap-2">
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Ask a question about your indexed documents..."
                className="flex-1 bg-neutral-900 border border-neutral-800 rounded-lg px-4 py-2.5 text-xs text-neutral-200 focus:outline-none focus:border-[#D4AF37]"
              />
              <button
                type="submit"
                disabled={isSearching}
                className="px-4 py-2.5 bg-[#D4AF37] text-black font-semibold rounded-lg text-xs hover:bg-[#E5C158] disabled:opacity-50 transition-all flex items-center gap-1.5"
              >
                {isSearching ? "Thinking..." : <Send size={14} />}
              </button>
            </form>
          </div>
        )}
      </main>

      {/* RIGHT SIDEBAR: Knowledge Base & Stepper */}
      <aside className="w-80 border-l border-neutral-800 bg-[#111111] flex flex-col p-4 gap-4 select-none">
        <div className="flex items-center gap-2 border-b border-neutral-800 pb-3">
          <Database size={16} className="text-[#D4AF37]" />
          <h2 className="text-xs font-semibold tracking-wide text-neutral-200 uppercase">Knowledge Base</h2>
        </div>

        {/* File Drag and Drop / Upload Area */}
        <div className="space-y-2">
          <span className="text-xs font-medium text-neutral-400">Add Sources</span>
          <label className="border-2 border-dashed border-neutral-800 hover:border-[#D4AF37]/50 rounded-xl p-6 flex flex-col items-center justify-center gap-2 bg-neutral-950/40 cursor-pointer transition-all">
            <UploadCloud size={20} className="text-neutral-500" />
            <span className="text-xs font-medium text-neutral-300">Drop files or click to upload</span>
            <span className="text-[10px] text-neutral-500">PDF documents supported</span>
            <input
              type="file"
              accept=".pdf"
              className="hidden"
              onChange={(e) => {
                const selected = e.target.files?.[0];
                if (selected) handleIngestStream(selected);
              }}
            />
          </label>
        </div>

        {/* Interactive Ingestion Stepper */}
        {ingestStep > 0 && (
          <IngestionStepper currentStep={ingestStep} errorMsg={ingestError} />
        )}

        {/* Uploaded Sources List */}
        <div className="flex-1 overflow-y-auto space-y-2 pt-2 border-t border-neutral-800">
          <span className="text-xs font-medium text-neutral-400">Sources ({uploadedSources.length})</span>
          {uploadedSources.length === 0 ? (
            <p className="text-xs text-neutral-600 italic">No sources added yet</p>
          ) : (
            uploadedSources.map((s, idx) => (
              <div key={idx} className="flex items-center gap-2 p-2 rounded-lg bg-neutral-900 border border-neutral-800 text-xs text-neutral-300">
                <FileText size={14} className="text-[#D4AF37]" />
                <span className="truncate">{s}</span>
              </div>
            ))
          )}
        </div>
      </aside>

    </div>
  );
}