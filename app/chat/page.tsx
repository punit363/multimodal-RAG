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
  Trash2,
  Loader2,
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
  id: string;
  title: string;
  messages: ChatMessage[];
}

interface DocumentItem {
  id: string;
  filename: string;
  created_at?: string;
}

export default function ChatWorkspace() {
  const [ingestStep, setIngestStep] = useState<number>(0);
  const [ingestError, setIngestError] = useState<string>("");

  // Knowledge base
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [selectedDocIds, setSelectedDocIds] = useState<Set<string>>(new Set());
  const [deletingDocId, setDeletingDocId] = useState<string | null>(null);
  const knownDocIdsRef = useRef<Set<string>>(new Set());

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [isSearching, setIsSearching] = useState(false);

  const [activeLightbox, setActiveLightbox] = useState<LightboxData | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const activeConversation = conversations.find((c) => c.id === activeConversationId);

  const noSourceSelected = documents.length > 0 && selectedDocIds.size === 0;

  // Initial load: conversations + documents from the backend
  useEffect(() => {
    fetchConversations();
    fetchDocuments();
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activeConversation?.messages]);

  const fetchConversations = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/conversations`);
      if (res.ok) {
        const data: Conversation[] = await res.json();
        setConversations(data);
        if (data.length > 0 && !activeConversationId) {
          setActiveConversationId(data[0].id);
        }
      }
    } catch (err) {
      console.error("Failed to load conversations:", err);
    }
  };

  // Load the document list. Newly seen documents are selected automatically;
  // documents that no longer exist are dropped from the selection.
  const fetchDocuments = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/documents`);
      if (!res.ok) return;
      const data: DocumentItem[] = await res.json();

      const newIds = data
        .filter((d) => !knownDocIdsRef.current.has(d.id))
        .map((d) => d.id);
      const currentIds = new Set(data.map((d) => d.id));
      knownDocIdsRef.current = currentIds;

      setDocuments(data);
      setSelectedDocIds((prev) => {
        const next = new Set<string>();
        prev.forEach((id) => currentIds.has(id) && next.add(id));
        newIds.forEach((id) => next.add(id));
        return next;
      });
    } catch (err) {
      console.error("Failed to load documents:", err);
    }
  };

  const toggleDocument = (id: string) => {
    setSelectedDocIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAllDocuments = () => {
    setSelectedDocIds((prev) =>
      prev.size === documents.length ? new Set() : new Set(documents.map((d) => d.id))
    );
  };

  const handleDeleteDocument = async (doc: DocumentItem) => {
    if (!window.confirm(`Delete "${doc.filename}" and remove it from the knowledge base?`)) {
      return;
    }
    setDeletingDocId(doc.id);
    try {
      const res = await fetch(`${API_BASE_URL}/api/documents/${doc.id}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error(`Delete failed (${res.status})`);
      await fetchDocuments();
    } catch (err) {
      console.error("Failed to delete document:", err);
      window.alert("Could not delete the document. Check the backend logs.");
    } finally {
      setDeletingDocId(null);
    }
  };

  // Document Upload Stream Handler
  const handleIngestStream = async (selectedFile: File) => {
    setIngestStep(1);
    setIngestError("");

    const formData = new FormData();
    formData.append("file", selectedFile);

    try {
      const response = await fetch(`${API_BASE_URL}/api/ingest-stream`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const detail = await response.json().catch(() => null);
        throw new Error(detail?.detail || `Upload failed (${response.status})`);
      }
      if (!response.body) throw new Error("No response body from ingestion stream");

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let failed = false;

      while (!failed) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const data = JSON.parse(line.replace("data: ", "").trim());
            if (data.status === "error") {
              setIngestError(data.label);
              failed = true;
              break;
            }
            setIngestStep(data.step);
            if (data.status === "completed") {
              // Pull the persisted list so the new doc shows up (and is selected)
              await fetchDocuments();
            }
          } catch (err) {
            console.error("Error parsing ingestion SSE line:", err);
          }
        }
      }
    } catch (err: any) {
      setIngestError(err.message || "Failed to process document.");
    }
  };

  // Create new conversation on server
  const startNewConversation = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/conversations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: `Conversation ${conversations.length + 1}` }),
      });
      if (res.ok) {
        const newConv: Conversation = await res.json();
        setConversations((prev) => [newConv, ...prev]);
        setActiveConversationId(newConv.id);
        setQuery("");
      }
    } catch (err) {
      console.error("Failed to create conversation:", err);
    }
  };

  // Search Query Handler
  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim() || isSearching || noSourceSelected) return;

    let convId = activeConversationId;

    // Ensure conversation exists in SQLite before starting message stream
    if (!convId) {
      try {
        const res = await fetch(`${API_BASE_URL}/api/conversations`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title: query.slice(0, 20) }),
        });
        const newConv: Conversation = await res.json();
        convId = newConv.id;
        setConversations((prev) => [newConv, ...prev]);
        setActiveConversationId(convId);
      } catch (err) {
        console.error("Failed to auto-create conversation in SQLite:", err);
        return;
      }
    }

    const currentQuery = query;
    const selectedFilenames = documents
      .filter((d) => selectedDocIds.has(d.id))
      .map((d) => d.filename);

    setQuery("");
    setIsSearching(true);

    const userMessageId = `usr-${crypto.randomUUID()}`;
    const assistantMessageId = `ast-${crypto.randomUUID()}`;

    // Optimistically update local React UI state
    setConversations((prev) =>
      prev.map((c) => {
        if (c.id === convId) {
          return {
            ...c,
            messages: [
              ...c.messages,
              { id: userMessageId, role: "user", content: currentQuery },
              { id: assistantMessageId, role: "assistant", content: "", sources: [] },
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
        body: JSON.stringify({
          query: currentQuery,
          conversation_id: convId,
          user_message_id: userMessageId,
          assistant_message_id: assistantMessageId,
          top_k: 3,
          sources: selectedFilenames,
        }),
      });

      if (!response.ok || !response.body) throw new Error("Stream connection failed");

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
                  prev.map((c) =>
                    c.id === convId
                      ? {
                          ...c,
                          messages: c.messages.map((m) =>
                            m.id === assistantMessageId ? { ...m, sources: data.sources } : m
                          ),
                        }
                      : c
                  )
                );
              } else if (data.type === "token") {
                setConversations((prev) =>
                  prev.map((c) =>
                    c.id === convId
                      ? {
                          ...c,
                          messages: c.messages.map((m) =>
                            m.id === assistantMessageId ? { ...m, content: m.content + data.token } : m
                          ),
                        }
                      : c
                  )
                );
              }
            } catch (err) {
              console.error("Error parsing SSE packet:", err);
            }
          }
        }
      }
    } catch (err: any) {
      console.error("Stream error:", err);
    } finally {
      setIsSearching(false);
    }
  };

  return (
    <div className="flex h-screen w-full bg-neutral-100 dark:bg-[#0D0D0D] text-neutral-900 dark:text-neutral-100 overflow-hidden font-sans">

      {/* LEFT SIDEBAR */}
      <aside className="w-64 border-r border-neutral-200 dark:border-neutral-800 bg-white dark:bg-[#111111] flex flex-col p-4 gap-4 select-none">
        <div className="flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2 font-bold text-sm tracking-wide text-neutral-800 dark:text-neutral-200 hover:text-[#D4AF37]">
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

        {/* Saved Conversations List */}
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

      {/* CENTER WORKSPACE */}
      <main className="flex-1 flex flex-col bg-white dark:bg-[#0A0A0A] relative overflow-hidden">
        <header className="h-14 border-b border-neutral-200 dark:border-neutral-800 flex items-center justify-between px-6 bg-neutral-50 dark:bg-[#0D0D0D]">
          <div>
            <h1 className="text-sm font-semibold text-neutral-800 dark:text-neutral-200">
              GenAI Team Workspace
            </h1>
            <p className="text-[11px] text-neutral-500">
              Multi-modal knowledge reasoning
              {documents.length > 0 && ` · ${selectedDocIds.size} of ${documents.length} sources active`}
            </p>
          </div>
          <button
            onClick={startNewConversation}
            className="flex items-center gap-1.5 py-1.5 px-3 rounded-md bg-neutral-900 text-white dark:bg-neutral-100 dark:text-black hover:bg-[#D4AF37] text-xs font-semibold transition-all cursor-pointer"
          >
            <Plus size={14} /> New conversation
          </button>
        </header>

        {/* Chat Messages Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {!activeConversation || activeConversation.messages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center space-y-4 max-w-md mx-auto">
              <div className="w-12 h-12 rounded-xl border border-neutral-300 dark:border-neutral-800 bg-neutral-100 dark:bg-neutral-900 flex items-center justify-center text-neutral-500">
                <MessageSquare size={20} />
              </div>
              <div className="space-y-1">
                <h3 className="text-sm font-semibold text-neutral-800 dark:text-neutral-200">
                  No messages in this project
                </h3>
                <p className="text-xs text-neutral-500 leading-relaxed">
                  Ask a question to start analyzing your uploaded documents.
                </p>
              </div>
            </div>
          ) : (
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
                      <div className="w-7 h-7 rounded-full bg-neutral-800 text-[#D4AF37] flex items-center justify-center font-bold text-xs shrink-0 border border-[#D4AF37]/40">
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
                                  onOpenLightbox={(data) => setActiveLightbox(data)}
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

        {/* Input Form */}
        <div className="p-4 border-t border-neutral-200 dark:border-neutral-800 bg-neutral-50 dark:bg-[#0D0D0D]">
          <form onSubmit={handleSearch} className="max-w-3xl mx-auto flex gap-2">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              disabled={noSourceSelected}
              placeholder={
                noSourceSelected
                  ? "Select at least one source in the Knowledge Base..."
                  : "Ask a question about your selected documents..."
              }
              className="flex-1 bg-white dark:bg-neutral-900 border border-neutral-300 dark:border-neutral-800 rounded-lg px-4 py-2.5 text-xs text-neutral-900 dark:text-neutral-200 focus:outline-none focus:border-[#D4AF37] disabled:opacity-60"
            />
            <button
              type="submit"
              disabled={isSearching || !query.trim() || noSourceSelected}
              className="px-4 py-2.5 bg-[#D4AF37] text-black font-semibold rounded-lg text-xs hover:bg-[#E5C158] disabled:opacity-50 transition-all flex items-center gap-1.5 cursor-pointer"
            >
              {isSearching ? "Thinking..." : <Send size={14} />}
            </button>
          </form>
        </div>
      </main>

      {/* RIGHT SIDEBAR */}
      <aside className="w-80 border-l border-neutral-200 dark:border-neutral-800 bg-white dark:bg-[#111111] flex flex-col p-4 gap-4 select-none">
        <div className="flex items-center gap-2 border-b border-neutral-200 dark:border-neutral-800 pb-3">
          <Database size={16} className="text-[#D4AF37]" />
          <h2 className="text-xs font-semibold tracking-wide text-neutral-800 dark:text-neutral-200 uppercase">
            Knowledge Base
          </h2>
        </div>

        <div className="space-y-2">
          <span className="text-xs font-medium text-neutral-600 dark:text-neutral-400">Add Sources</span>
          <label className="border-2 border-dashed border-neutral-300 dark:border-neutral-800 hover:border-[#D4AF37]/50 rounded-xl p-6 flex flex-col items-center justify-center gap-2 bg-neutral-50 dark:bg-neutral-950/40 cursor-pointer transition-all">
            <UploadCloud size={20} className="text-neutral-500" />
            <span className="text-xs font-medium text-neutral-700 dark:text-neutral-300">Drop files or click to upload</span>
            <span className="text-[10px] text-neutral-500">PDF documents supported</span>
            <input
              type="file"
              accept=".pdf"
              className="hidden"
              onChange={(e) => {
                const selected = e.target.files?.[0];
                if (selected) {
                  handleIngestStream(selected);
                }
                // allow re-uploading the same file
                e.target.value = "";
              }}
            />
          </label>
        </div>

        {ingestStep > 0 && <IngestionStepper currentStep={ingestStep} errorMsg={ingestError} />}

        <div className="flex-1 overflow-y-auto space-y-2 pt-2 border-t border-neutral-200 dark:border-neutral-800">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-neutral-600 dark:text-neutral-400">
              Sources ({documents.length})
            </span>
            {documents.length > 0 && (
              <button
                onClick={toggleAllDocuments}
                className="text-[10px] font-medium text-[#D4AF37] hover:underline cursor-pointer"
              >
                {selectedDocIds.size === documents.length ? "Deselect all" : "Select all"}
              </button>
            )}
          </div>

          {documents.length === 0 ? (
            <p className="text-xs text-neutral-500 dark:text-neutral-600 italic">No sources added yet</p>
          ) : (
            documents.map((doc) => {
              const isSelected = selectedDocIds.has(doc.id);
              const isDeleting = deletingDocId === doc.id;
              return (
                <div
                  key={doc.id}
                  className={`flex items-center gap-2 p-2 rounded-lg border text-xs transition-colors ${
                    isSelected
                      ? "bg-amber-500/10 border-[#D4AF37]/40 text-neutral-900 dark:text-neutral-100"
                      : "bg-neutral-100 dark:bg-neutral-900 border-neutral-200 dark:border-neutral-800 text-neutral-600 dark:text-neutral-400"
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => toggleDocument(doc.id)}
                    disabled={isDeleting}
                    className="accent-[#D4AF37] cursor-pointer shrink-0"
                    aria-label={`Use ${doc.filename} as a source`}
                  />
                  <FileText size={14} className="text-[#D4AF37] shrink-0" />
                  <span className="truncate flex-1" title={doc.filename}>
                    {doc.filename}
                  </span>
                  <button
                    onClick={() => handleDeleteDocument(doc)}
                    disabled={isDeleting}
                    className="p-1 rounded text-neutral-500 hover:text-red-500 hover:bg-red-500/10 disabled:opacity-50 cursor-pointer shrink-0"
                    aria-label={`Delete ${doc.filename}`}
                    title="Delete document"
                  >
                    {isDeleting ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
                  </button>
                </div>
              );
            })
          )}
        </div>
      </aside>

      <CitationLightbox data={activeLightbox} onClose={() => setActiveLightbox(null)} />
    </div>
  );
}