// app/chat/page.tsx
"use client";

import React, { useState, useRef, useEffect } from "react";
import Link from "next/link";
import { ThemeToggle } from "@/components/ThemeToggle";
import { IngestionStepper } from "@/components/IngestionStepper";
import { SourceCitationCard } from "@/components/SourceCitationCard";
import { RetrievedChunk } from "@/types/rag";
import {
  Plus,
  Folder,
  UploadCloud,
  MessageSquare,
  FileText,
  Send,
  Database,
  ArrowLeft,
  User,
  Bot,
} from "lucide-react";
import { CitationLightbox, LightboxData } from "@/components/CitationLightbox";

const API_BASE_URL = "http://localhost:8000";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: RetrievedChunk[];
}

interface Conversation {
  id: number;
  title: string;
  messages: ChatMessage[];
}

export default function ChatWorkspace() {
  // Navigation & File Ingestion States
  const [file, setFile] = useState<File | null>(null);
  const [ingestStep, setIngestStep] = useState<number>(0);
  const [ingestError, setIngestError] = useState<string>("");
  const [uploadedSources, setUploadedSources] = useState<string[]>([]);

  // Conversation & Chat History States
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<
    number | null
  >(null);
  const [query, setQuery] = useState("");
  const [isSearching, setIsSearching] = useState(false);

  // Lightbox State
  const [activeLightbox, setActiveLightbox] = useState<LightboxData | null>(
    null
  );

  // Auto-scroll ref
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const activeConversation = conversations.find(
    (c) => c.id === activeConversationId
  );

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activeConversation?.messages]);

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

      if (!response.body)
        throw new Error("No response body from ingestion stream");

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

  // Start new conversation
  const startNewConversation = () => {
    const newId = conversations.length + 1;
    const newConv: Conversation = {
      id: newId,
      title: `Conversation ${newId}`,
      messages: [],
    };
    setConversations((prev) => [...prev, newConv]);
    setActiveConversationId(newId);
    setQuery("");
  };

  // Handle Search Query with streaming history
  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim() || isSearching) return;

    let convId = activeConversationId;
    if (!convId) {
      const newId = conversations.length + 1;
      const newConv: Conversation = {
        id: newId,
        title: query.length > 20 ? `${query.slice(0, 20)}...` : query,
        messages: [],
      };
      setConversations((prev) => [...prev, newConv]);
      setActiveConversationId(newId);
      convId = newId;
    }

    const currentQuery = query;
    setQuery(""); // Clear input box immediately
    setIsSearching(true);

    const userMessageId = `user-${Date.now()}`;
    const assistantMessageId = `assistant-${Date.now()}`;

    // Append User Message and empty Assistant Message shell
    setConversations((prev) =>
      prev.map((c) => {
        if (c.id === convId) {
          return {
            ...c,
            title:
              c.messages.length === 0
                ? currentQuery.length > 22
                  ? `${currentQuery.slice(0, 22)}...`
                  : currentQuery
                : c.title,
            messages: [
              ...c.messages,
              { id: userMessageId, role: "user", content: currentQuery },
              {
                id: assistantMessageId,
                role: "assistant",
                content: "",
                sources: [],
              },
            ],
          };
        }
        return c;
      })
    );

    try {
      const response = await fetch(`${API_BASE_URL}/api/chat-stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: currentQuery, top_k: 3 }),
      });

      if (!response.ok || !response.body) {
        throw new Error("Failed to start stream");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const data = JSON.parse(line.replace("data: ", ""));

              if (data.type === "sources") {
                setConversations((prev) =>
                  prev.map((c) => {
                    if (c.id === convId) {
                      return {
                        ...c,
                        messages: c.messages.map((m) =>
                          m.id === assistantMessageId
                            ? { ...m, sources: data.sources }
                            : m
                        ),
                      };
                    }
                    return c;
                  })
                );
              } else if (data.type === "token") {
                setConversations((prev) =>
                  prev.map((c) => {
                    if (c.id === convId) {
                      return {
                        ...c,
                        messages: c.messages.map((m) =>
                          m.id === assistantMessageId
                            ? { ...m, content: m.content + data.token }
                            : m
                        ),
                      };
                    }
                    return c;
                  })
                );
              }
            } catch (err) {
              console.error("Error parsing SSE line:", err);
            }
          }
        }
      }
    } catch (err: any) {
      setConversations((prev) =>
        prev.map((c) => {
          if (c.id === convId) {
            return {
              ...c,
              messages: c.messages.map((m) =>
                m.id === assistantMessageId
                  ? {
                      ...m,
                      content: `Error: ${err.message || "Streaming failed"}`,
                    }
                  : m
              ),
            };
          }
          return c;
        })
      );
    } finally {
      setIsSearching(false);
    }
  };

  return (
    <div className="flex h-screen w-full bg-neutral-100 dark:bg-[#0D0D0D] text-neutral-900 dark:text-neutral-100 overflow-hidden font-sans transition-colors duration-300">
      {/* LEFT SIDEBAR: Navigation & Projects */}
      <aside className="w-64 border-r border-neutral-200 dark:border-neutral-800 bg-white dark:bg-[#111111] flex flex-col p-4 gap-4 select-none">
        <div className="flex items-center justify-between">
          <Link
            href="/"
            className="flex items-center gap-2 font-bold text-sm tracking-wide text-neutral-800 dark:text-neutral-200 hover:text-[#D4AF37]"
          >
            <ArrowLeft size={16} /> MultiModal.RAG
          </Link>
          <ThemeToggle />
        </div>

        <button
          onClick={startNewConversation}
          className="flex items-center justify-center gap-2 w-full py-2 px-3 rounded-lg border border-neutral-300 dark:border-neutral-700 bg-neutral-100 dark:bg-neutral-900 hover:bg-neutral-200 dark:hover:bg-neutral-800 text-xs font-semibold text-neutral-800 dark:text-neutral-200 transition-all cursor-pointer"
        >
          <Plus size={14} /> New project
        </button>

        <div className="space-y-1 text-xs text-neutral-500 dark:text-neutral-400">
          <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-neutral-100 dark:bg-neutral-900/50 text-neutral-800 dark:text-neutral-200 font-medium">
            <Folder size={14} className="text-[#D4AF37]" />
            <span>Projects</span>
          </div>
        </div>

        {/* Existing Conversations List */}
        <div className="flex-1 overflow-y-auto space-y-1 pt-2">
          {conversations.map((c) => (
            <div
              key={c.id}
              onClick={() => setActiveConversationId(c.id)}
              className={`flex items-center gap-2 px-3 py-2 rounded-lg text-xs cursor-pointer transition-colors ${
                activeConversationId === c.id
                  ? "bg-amber-500/10 text-[#D4AF37] font-semibold"
                  : "text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-900 hover:text-neutral-900 dark:hover:text-neutral-200"
              }`}
            >
              <MessageSquare size={13} />
              <span className="truncate">{c.title}</span>
            </div>
          ))}
        </div>
      </aside>

      {/* CENTER WORKSPACE: Main Chat Area */}
      <main className="flex-1 flex flex-col bg-white dark:bg-[#0A0A0A] relative overflow-hidden">
        {/* Workspace Header */}
        <header className="h-14 border-b border-neutral-200 dark:border-neutral-800 flex items-center justify-between px-6 bg-neutral-50 dark:bg-[#0D0D0D]">
          <div>
            <h1 className="text-sm font-semibold text-neutral-800 dark:text-neutral-200">
              GenAI Team Workspace
            </h1>
            <p className="text-[11px] text-neutral-500">
              Multi-modal knowledge reasoning
            </p>
          </div>
          <button
            onClick={startNewConversation}
            className="flex items-center gap-1.5 py-1.5 px-3 rounded-md bg-neutral-900 text-white dark:bg-neutral-100 dark:text-black hover:bg-[#D4AF37] dark:hover:bg-[#D4AF37] text-xs font-semibold transition-all cursor-pointer"
          >
            <Plus size={14} /> New conversation
          </button>
        </header>

        {/* Workspace Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {!activeConversation || activeConversation.messages.length === 0 ? (
            /* Empty State */
            <div className="h-full flex flex-col items-center justify-center text-center space-y-4 max-w-md mx-auto">
              <div className="w-12 h-12 rounded-xl border border-neutral-300 dark:border-neutral-800 bg-neutral-100 dark:bg-neutral-900 flex items-center justify-center text-neutral-500">
                <MessageSquare size={20} />
              </div>
              <div className="space-y-1">
                <h3 className="text-sm font-semibold text-neutral-800 dark:text-neutral-200">
                  No conversations yet
                </h3>
                <p className="text-xs text-neutral-500 leading-relaxed">
                  Start your first conversation in this project to analyze
                  documents and get multi-modal insights.
                </p>
              </div>
              <button
                onClick={startNewConversation}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-neutral-900 text-white dark:bg-neutral-100 dark:text-black text-xs font-semibold hover:bg-[#D4AF37] dark:hover:bg-[#D4AF37] transition-all cursor-pointer shadow-lg"
              >
                <Plus size={14} /> Start first conversation
              </button>
            </div>
          ) : (
            /* Active Chat Stream History */
            <div className="max-w-3xl mx-auto space-y-6">
              {activeConversation.messages.map((msg) => (
                <div key={msg.id} className="space-y-4">
                  {msg.role === "user" ? (
                    <div className="flex items-start gap-3 justify-end">
                      <div className="bg-amber-500/10 border border-[#D4AF37]/30 text-neutral-900 dark:text-neutral-100 px-4 py-3 rounded-2xl max-w-xl text-xs leading-relaxed">
                        {msg.content}
                      </div>
                      <div className="w-7 h-7 rounded-full bg-[#D4AF37] text-black flex items-center justify-center font-bold text-xs shrink-0">
                        <User size={14} />
                      </div>
                    </div>
                  ) : (
                    <div className="flex items-start gap-3">
                      <div className="w-7 h-7 rounded-full bg-neutral-800 dark:bg-neutral-800 text-[#D4AF37] flex items-center justify-center font-bold text-xs shrink-0 border border-[#D4AF37]/40">
                        <Bot size={14} />
                      </div>
                      <div className="space-y-4 flex-1">
                        {msg.content ? (
                          <div className="border border-neutral-200 dark:border-neutral-800 rounded-xl p-4 bg-neutral-50 dark:bg-neutral-900/40 text-xs text-neutral-800 dark:text-neutral-200 leading-relaxed whitespace-pre-wrap">
                            <span className="text-[10px] font-mono uppercase tracking-widest text-[#D4AF37] block mb-2">
                              Generated Answer
                            </span>
                            {msg.content}
                          </div>
                        ) : (
                          <div className="text-xs text-neutral-500 animate-pulse italic">
                            Thinking & generating answer...
                          </div>
                        )}

                        {msg.sources && msg.sources.length > 0 && (
                          <div className="space-y-2">
                            <span className="text-xs font-mono uppercase tracking-wider text-neutral-500">
                              Retrieved Sources ({msg.sources.length})
                            </span>
                            <div className="grid gap-3">
                              {msg.sources.map((chunk) => (
                                <SourceCitationCard
                                  key={chunk.chunk_id}
                                  chunk={chunk}
                                  onOpenLightbox={(data) =>
                                    setActiveLightbox(data)
                                  }
                                />
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              ))}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        {/* Input Query Bar */}
        <div className="p-4 border-t border-neutral-200 dark:border-neutral-800 bg-neutral-50 dark:bg-[#0D0D0D]">
          <form
            onSubmit={handleSearch}
            className="max-w-3xl mx-auto flex gap-2"
          >
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Ask a question about your indexed documents..."
              className="flex-1 bg-white dark:bg-neutral-900 border border-neutral-300 dark:border-neutral-800 rounded-lg px-4 py-2.5 text-xs text-neutral-900 dark:text-neutral-200 focus:outline-none focus:border-[#D4AF37]"
            />
            <button
              type="submit"
              disabled={isSearching || !query.trim()}
              className="px-4 py-2.5 bg-[#D4AF37] text-black font-semibold rounded-lg text-xs hover:bg-[#E5C158] disabled:opacity-50 transition-all flex items-center gap-1.5 cursor-pointer"
            >
              {isSearching ? "Thinking..." : <Send size={14} />}
            </button>
          </form>
        </div>
      </main>

      {/* RIGHT SIDEBAR: Knowledge Base & Stepper */}
      <aside className="w-80 border-l border-neutral-200 dark:border-neutral-800 bg-white dark:bg-[#111111] flex flex-col p-4 gap-4 select-none">
        <div className="flex items-center gap-2 border-b border-neutral-200 dark:border-neutral-800 pb-3">
          <Database size={16} className="text-[#D4AF37]" />
          <h2 className="text-xs font-semibold tracking-wide text-neutral-800 dark:text-neutral-200 uppercase">
            Knowledge Base
          </h2>
        </div>

        {/* File Drag and Drop / Upload Area */}
        <div className="space-y-2">
          <span className="text-xs font-medium text-neutral-600 dark:text-neutral-400">
            Add Sources
          </span>
          <label className="border-2 border-dashed border-neutral-300 dark:border-neutral-800 hover:border-[#D4AF37]/50 rounded-xl p-6 flex flex-col items-center justify-center gap-2 bg-neutral-50 dark:bg-neutral-950/40 cursor-pointer transition-all">
            <UploadCloud size={20} className="text-neutral-500" />
            <span className="text-xs font-medium text-neutral-700 dark:text-neutral-300">
              Drop files or click to upload
            </span>
            <span className="text-[10px] text-neutral-500">
              PDF documents supported
            </span>
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
        <div className="flex-1 overflow-y-auto space-y-2 pt-2 border-t border-neutral-200 dark:border-neutral-800">
          <span className="text-xs font-medium text-neutral-600 dark:text-neutral-400">
            Sources ({uploadedSources.length})
          </span>
          {uploadedSources.length === 0 ? (
            <p className="text-xs text-neutral-500 dark:text-neutral-600 italic">
              No sources added yet
            </p>
          ) : (
            uploadedSources.map((s, idx) => (
              <div
                key={idx}
                className="flex items-center gap-2 p-2 rounded-lg bg-neutral-100 dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-800 text-xs text-neutral-800 dark:text-neutral-300"
              >
                <FileText size={14} className="text-[#D4AF37]" />
                <span className="truncate">{s}</span>
              </div>
            ))
          )}
        </div>
      </aside>

      <CitationLightbox
        data={activeLightbox}
        onClose={() => setActiveLightbox(null)}
      />
    </div>
  );
}
