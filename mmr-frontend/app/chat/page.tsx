// app/chat/page.tsx
"use client";

import React, { useState, useRef, useEffect, useCallback } from "react";
import Link from "next/link";
import { ThemeToggle } from "@/components/ThemeToggle";
import { IngestionStepper } from "@/components/IngestionStepper";
import { SourceCitationCard } from "@/components/SourceCitationCard";
import { AnswerWithCitations } from "@/components/AnswerWithCitations";
import { AnswerFeedback, AnswerRating } from "@/components/AnswerFeedback";
import { AnswerActions } from "@/components/AnswerActions";
import { PdfCitationViewer } from "@/components/PdfCitationViewer";
import { RetrievedChunk } from "@/types/rag";
import { API_BASE_URL, fetchWithTimeout } from "@/lib/api";
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
  RotateCcw,
  XCircle,
} from "lucide-react";
import { CitationLightbox, LightboxData } from "@/components/CitationLightbox";

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: RetrievedChunk[];
  feedback?: AnswerRating;
}

interface Conversation {
  id: string;
  title: string;
  messages: ChatMessage[];
}

interface DocumentItem {
  id: string;
  filename: string;
  source_id?: string;
  status?: "processing" | "ready" | "failed" | "deleting" | "deletion_failed";
  error?: string;
  created_at?: string;
  tags?: string[];
}

export default function ChatWorkspace() {
  const [ingestStep, setIngestStep] = useState<number>(0);
  const [ingestError, setIngestError] = useState<string>("");
  const [isIngesting, setIsIngesting] = useState(false);
  const [lastIngestFile, setLastIngestFile] = useState<File | null>(null);
  const ingestControllerRef = useRef<AbortController | null>(null);

  // Knowledge base
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [selectedDocIds, setSelectedDocIds] = useState<Set<string>>(new Set());
  const [filterPage, setFilterPage] = useState("");
  const [filterContentType, setFilterContentType] = useState("");
  const [filterCreatedFrom, setFilterCreatedFrom] = useState("");
  const [filterCreatedTo, setFilterCreatedTo] = useState("");
  const [filterTag, setFilterTag] = useState("");
  const [comparisonMode, setComparisonMode] = useState(false);
  const [deletingDocId, setDeletingDocId] = useState<string | null>(null);
  const knownDocIdsRef = useRef<Set<string>>(new Set());

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [isSearching, setIsSearching] = useState(false);
  const [activeAssistantMessageId, setActiveAssistantMessageId] = useState<string | null>(null);
  const [isStopping, setIsStopping] = useState(false);
  const [chatError, setChatError] = useState("");
  const [feedbackPendingId, setFeedbackPendingId] = useState<string | null>(null);
  const [feedbackError, setFeedbackError] = useState("");
  const [lastFailedQuery, setLastFailedQuery] = useState("");
  const chatControllerRef = useRef<AbortController | null>(null);
  const [workspaceError, setWorkspaceError] = useState("");
  const [failedDelete, setFailedDelete] = useState<DocumentItem | null>(null);

  const [activeLightbox, setActiveLightbox] = useState<LightboxData | null>(null);
  const [activePdfSource, setActivePdfSource] = useState<RetrievedChunk | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const activeConversation = conversations.find((c) => c.id === activeConversationId);
  const readyDocuments = documents.filter((doc) => !doc.status || doc.status === "ready");
  const availableTags = [...new Set(readyDocuments.flatMap((doc) => doc.tags || []))].sort();

  const noSourceSelected = readyDocuments.length === 0 || selectedDocIds.size === 0;

  const openPdfSource = (chunk: RetrievedChunk) => {
    const registeredDocument = documents.find(
      (document) =>
        document.id === chunk.document_id || document.source_id === chunk.document_id
    );
    setActivePdfSource({
      ...chunk,
      document_id: registeredDocument?.id || chunk.document_id,
    });
  };

  const updateAnswerFeedback = async (messageId: string, feedback: AnswerRating) => {
    setFeedbackPendingId(messageId);
    setFeedbackError("");
    try {
      const response = await fetchWithTimeout(`${API_BASE_URL}/api/messages/${encodeURIComponent(messageId)}/feedback`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ feedback }),
      });
      if (!response.ok) throw new Error(`Could not save feedback (${response.status}).`);
      setConversations((previous) => previous.map((conversation) => ({
        ...conversation,
        messages: conversation.messages.map((message) => message.id === messageId ? { ...message, feedback } : message),
      })));
    } catch (error) {
      setFeedbackError(getErrorMessage(error, "Could not save feedback."));
    } finally {
      setFeedbackPendingId(null);
    }
  };

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activeConversation?.messages]);

  const fetchConversations = useCallback(async () => {
    try {
      const res = await fetchWithTimeout(`${API_BASE_URL}/api/conversations`);
      if (res.ok) {
        const data: Conversation[] = await res.json();
        setConversations(data);
        setActiveConversationId((current) => current ?? data[0]?.id ?? null);
      } else {
        throw new Error(`Could not load conversations (${res.status}).`);
      }
    } catch (err: unknown) {
      setWorkspaceError(getErrorMessage(err, "Could not load conversations."));
    }
  }, []);

  // Load the document list. Newly seen documents are selected automatically;
  // documents that no longer exist are dropped from the selection.
  const fetchDocuments = useCallback(async () => {
    try {
      const res = await fetchWithTimeout(`${API_BASE_URL}/api/documents`);
      if (!res.ok) throw new Error(`Could not load documents (${res.status}).`);
      const data: DocumentItem[] = await res.json();

      const newIds = data
        .filter(
          (d) => (!d.status || d.status === "ready") && !knownDocIdsRef.current.has(d.id)
        )
        .map((d) => d.id);
      const currentIds = new Set(
        data.filter((d) => !d.status || d.status === "ready").map((d) => d.id)
      );
      knownDocIdsRef.current = currentIds;

      setDocuments(data);
      setSelectedDocIds((prev) => {
        const next = new Set<string>();
        prev.forEach((id) => currentIds.has(id) && next.add(id));
        newIds.forEach((id) => next.add(id));
        return next;
      });
    } catch (err: unknown) {
      setWorkspaceError(getErrorMessage(err, "Could not load documents."));
    }
  }, []);

  // Initial load: conversations + documents from the backend
  useEffect(() => {
    const loadTimer = window.setTimeout(() => {
      void Promise.all([fetchConversations(), fetchDocuments()]);
    }, 0);

    return () => window.clearTimeout(loadTimer);
  }, [fetchConversations, fetchDocuments]);

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
      prev.size === readyDocuments.length
        ? new Set()
        : new Set(readyDocuments.map((d) => d.id))
    );
  };

  const handleDeleteDocument = async (doc: DocumentItem) => {
    if (!window.confirm(`Delete "${doc.filename}" and remove it from the knowledge base?`)) {
      return;
    }
    setDeletingDocId(doc.id);
    setWorkspaceError("");
    setFailedDelete(null);
    try {
      const res = await fetchWithTimeout(`${API_BASE_URL}/api/documents/${doc.id}`, {
        method: "DELETE",
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => null);
        throw new Error(detail?.detail || `Delete failed (${res.status})`);
      }
      await fetchDocuments();
    } catch (err: unknown) {
      setWorkspaceError(getErrorMessage(err, "Could not delete the document."));
      setFailedDelete(doc);
    } finally {
      setDeletingDocId(null);
    }
  };

  const editDocumentTags = async (doc: DocumentItem) => {
    const input = window.prompt(`Tags for ${doc.filename} (comma-separated)`, (doc.tags || []).join(", "));
    if (input === null) return;
    const tags = [...new Set(input.split(",").map((tag) => tag.trim()).filter(Boolean))];
    setWorkspaceError("");
    try {
      const response = await fetchWithTimeout(`${API_BASE_URL}/api/documents/${encodeURIComponent(doc.id)}/tags`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tags }),
      });
      if (!response.ok) throw new Error(`Could not save tags (${response.status}).`);
      await fetchDocuments();
    } catch (error) {
      setWorkspaceError(getErrorMessage(error, "Could not save tags."));
    }
  };

  // Document Upload Stream Handler
  const handleIngestStream = async (selectedFile: File) => {
    if (selectedFile.type !== "application/pdf" || !selectedFile.name.toLowerCase().endsWith(".pdf")) {
      setIngestStep(1);
      setIngestError("Choose a PDF file with the application/pdf MIME type.");
      setLastIngestFile(selectedFile);
      return;
    }
    if (selectedFile.size > 25 * 1024 * 1024) {
      setIngestStep(1);
      setIngestError("PDF exceeds the 25 MB upload limit.");
      setLastIngestFile(selectedFile);
      return;
    }

    setIngestStep(1);
    setIngestError("");
    setLastIngestFile(selectedFile);
    setIsIngesting(true);

    const formData = new FormData();
    formData.append("file", selectedFile);
    const controller = new AbortController();
    ingestControllerRef.current = controller;
    const timeout = window.setTimeout(
      () => controller.abort(new Error("Ingestion timed out.")),
      5 * 60 * 1000
    );

    try {
      const response = await fetch(`${API_BASE_URL}/api/ingest-stream`, {
        method: "POST",
        body: formData,
        signal: controller.signal,
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
              await reader.cancel();
              break;
            }
            setIngestStep(data.step);
            if (data.status === "completed") {
              setLastIngestFile(null);
              await fetchDocuments();
            }
          } catch (err) {
            console.error("Error parsing ingestion SSE line:", err);
          }
        }
      }
    } catch (err: unknown) {
      setIngestError(
        controller.signal.aborted
          ? "Ingestion was cancelled or timed out. You can retry safely."
          : getErrorMessage(err, "Failed to process document.")
      );
    } finally {
      window.clearTimeout(timeout);
      if (ingestControllerRef.current === controller) ingestControllerRef.current = null;
      setIsIngesting(false);
    }
  };

  const cancelIngestion = () => {
    ingestControllerRef.current?.abort(new Error("Cancelled by user."));
  };

  // Create new conversation on server
  const startNewConversation = async () => {
    setWorkspaceError("");
    try {
      const res = await fetchWithTimeout(`${API_BASE_URL}/api/conversations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: `Conversation ${conversations.length + 1}` }),
      });
      if (!res.ok) throw new Error(`Could not create conversation (${res.status}).`);
      const newConv: Conversation = await res.json();
      setConversations((prev) => [newConv, ...prev]);
      setActiveConversationId(newConv.id);
      setQuery("");
    } catch (err: unknown) {
      setWorkspaceError(getErrorMessage(err, "Could not create conversation."));
    }
  };

  const runSearch = async (currentQuery: string) => {
    if (!currentQuery.trim() || isSearching || noSourceSelected) return;
    const selectedReadyCount = readyDocuments.filter((document) => selectedDocIds.has(document.id)).length;
    if (comparisonMode && (selectedReadyCount < 2 || selectedReadyCount > 4)) {
      setChatError("Select two to four ready documents for comparison.");
      return;
    }
    if (filterCreatedFrom && filterCreatedTo && filterCreatedFrom > filterCreatedTo) {
      setChatError("The start date must be on or before the end date.");
      return;
    }
    setChatError("");
    setLastFailedQuery(currentQuery);

    let convId = activeConversationId;

    // Ensure conversation exists in SQLite before starting message stream
    if (!convId) {
      try {
        const res = await fetchWithTimeout(`${API_BASE_URL}/api/conversations`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title: currentQuery.slice(0, 20) }),
        });
        if (!res.ok) throw new Error(`Could not create conversation (${res.status}).`);
        const newConv: Conversation = await res.json();
        convId = newConv.id;
        setConversations((prev) => [newConv, ...prev]);
        setActiveConversationId(convId);
      } catch (err: unknown) {
        setChatError(getErrorMessage(err, "Could not create a conversation."));
        return;
      }
    }

    const selectedDocumentIds = documents
      .filter((d) => (!d.status || d.status === "ready") && selectedDocIds.has(d.id))
      .map((d) => d.source_id || d.id);

    setQuery("");
    setIsSearching(true);

    const userMessageId = `usr-${crypto.randomUUID()}`;
    const assistantMessageId = `ast-${crypto.randomUUID()}`;
    setActiveAssistantMessageId(assistantMessageId);
    setIsStopping(false);
    const controller = new AbortController();
    chatControllerRef.current = controller;
    const timeout = window.setTimeout(
      () => controller.abort(new Error("Answer generation timed out.")),
      2 * 60 * 1000
    );

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
          sources: selectedDocumentIds,
          mode: comparisonMode ? "compare" : "answer",
          filters: {
            pages: filterPage ? [Number(filterPage)] : [],
            content_types: filterContentType ? [filterContentType] : [],
            created_from: filterCreatedFrom || null,
            created_to: filterCreatedTo || null,
            tags: filterTag ? [filterTag] : [],
          },
        }),
        signal: controller.signal,
      });

      if (!response.ok) {
        const detail = await response.json().catch(() => null);
        throw new Error(detail?.detail || `Stream connection failed (${response.status}).`);
      }
      if (!response.body) throw new Error("The answer stream did not return a response body.");

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
            let data: { type?: string; sources?: RetrievedChunk[]; token?: string; message?: string };
            try {
              data = JSON.parse(line.replace("data: ", ""));
            } catch (err) {
              console.error("Error parsing SSE packet:", err);
              continue;
            }
            if (data.type === "sources") {
                setConversations((prev) =>
                  prev.map((c) =>
                    c.id === convId
                      ? {
                          ...c,
                          messages: c.messages.map((m) =>
                            m.id === assistantMessageId ? { ...m, sources: data.sources || [] } : m
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
                            m.id === assistantMessageId
                              ? { ...m, content: m.content + (data.token || "") }
                              : m
                          ),
                        }
                      : c
                  )
                );
            } else if (data.type === "error") {
              throw new Error(data.message || "Answer generation failed.");
            }
          }
        }
      }
    } catch (err: unknown) {
      const message = controller.signal.aborted
        ? "Answer generation was cancelled or timed out."
        : getErrorMessage(err, "Answer generation failed.");
      setChatError(message);
      setConversations((prev) =>
        prev.map((conversation) =>
          conversation.id === convId
            ? {
                ...conversation,
                messages: conversation.messages.map((messageItem) =>
                  messageItem.id === assistantMessageId && !messageItem.content
                    ? { ...messageItem, content: message }
                    : messageItem
                ),
              }
            : conversation
        )
      );
    } finally {
      window.clearTimeout(timeout);
      if (chatControllerRef.current === controller) chatControllerRef.current = null;
      setActiveAssistantMessageId(null);
      setIsStopping(false);
      setIsSearching(false);
    }
  };

  const handleSearch = (event: React.FormEvent) => {
    event.preventDefault();
    void runSearch(query);
  };

  const cancelChat = () => {
    setIsStopping(true);
    chatControllerRef.current?.abort(new Error("Cancelled by user."));
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

        {workspaceError && (
          <div className="mx-6 mt-4 flex items-center justify-between gap-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-500">
            <span className="flex items-center gap-2"><XCircle size={14} /> {workspaceError}</span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() =>
                  failedDelete
                    ? void handleDeleteDocument(failedDelete)
                    : void Promise.all([fetchConversations(), fetchDocuments()])
                }
                className="inline-flex items-center gap-1 font-semibold hover:underline"
              >
                <RotateCcw size={12} /> Retry
              </button>
              <button
                type="button"
                onClick={() => {
                  setWorkspaceError("");
                  setFailedDelete(null);
                }}
                aria-label="Dismiss error"
              >
                ×
              </button>
            </div>
          </div>
        )}

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
              {activeConversation.messages.map((msg, messageIndex) => (
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
                          <div className="border border-neutral-200 dark:border-neutral-800 rounded-xl p-4 bg-neutral-50 dark:bg-neutral-900/40 text-xs text-neutral-800 dark:text-neutral-200 leading-relaxed">
                            <span className="text-[10px] font-mono uppercase tracking-widest text-[#D4AF37] block mb-2">
                              Generated Answer
                            </span>
                            <AnswerWithCitations
                              text={msg.content}
                              sources={msg.sources || []}
                              onOpenPdf={openPdfSource}
                            />
                            <div className="mt-3 border-t border-neutral-200 pt-2 dark:border-neutral-800">
                              <AnswerActions answer={msg.content} messageId={msg.id} sources={msg.sources || []}
                                onRegenerate={!isSearching && !noSourceSelected && activeConversation.messages.slice(0, messageIndex).reverse().find((item) => item.role === "user")?.content
                                  ? () => void runSearch(activeConversation.messages.slice(0, messageIndex).reverse().find((item) => item.role === "user")!.content)
                                  : undefined}
                                isGenerating={activeAssistantMessageId === msg.id}
                                isStopping={isStopping}
                                onStop={cancelChat} />
                            </div>
                            <div className="mt-3 border-t border-neutral-200 pt-2 dark:border-neutral-800">
                              <AnswerFeedback feedback={msg.feedback || null} pending={feedbackPendingId === msg.id}
                                onChange={(feedback) => void updateAnswerFeedback(msg.id, feedback)} />
                            </div>
                          </div>
                        ) : (
                          <div className="space-y-2 text-xs text-neutral-500 italic">
                            <p className="animate-pulse">Thinking & generating answer...</p>
                            {activeAssistantMessageId === msg.id && <AnswerActions answer="" messageId={msg.id} sources={[]} isGenerating isStopping={isStopping} onStop={cancelChat} />}
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
                                  onOpenPdf={openPdfSource}
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
          <div className="max-w-3xl mx-auto mb-3 grid grid-cols-2 sm:grid-cols-5 gap-2 text-[11px]">
            <label className="flex flex-col gap-1">Page
              <input aria-label="Filter by page" type="number" min="1" value={filterPage} onChange={(event) => setFilterPage(event.target.value)} placeholder="Any" className="rounded border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-2 py-1" />
            </label>
            <label className="flex flex-col gap-1">Content
              <select aria-label="Filter by content type" value={filterContentType} onChange={(event) => setFilterContentType(event.target.value)} className="rounded border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-2 py-1">
                <option value="">Any</option><option value="text">Text</option><option value="table">Table</option><option value="image">Image</option>
              </select>
            </label>
            <label className="flex flex-col gap-1">Uploaded from
              <input aria-label="Filter from date" type="date" value={filterCreatedFrom} onChange={(event) => setFilterCreatedFrom(event.target.value)} className="rounded border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-2 py-1" />
            </label>
            <label className="flex flex-col gap-1">Uploaded through
              <input aria-label="Filter through date" type="date" value={filterCreatedTo} onChange={(event) => setFilterCreatedTo(event.target.value)} className="rounded border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-2 py-1" />
            </label>
            <label className="flex flex-col gap-1">Tag
              <select aria-label="Filter by tag" value={filterTag} onChange={(event) => setFilterTag(event.target.value)} className="rounded border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-2 py-1">
                <option value="">Any</option>{availableTags.map((tag) => <option key={tag} value={tag}>{tag}</option>)}
              </select>
            </label>
          </div>
          {feedbackError && <p role="alert" className="max-w-3xl mx-auto mb-2 text-xs text-red-500">{feedbackError}</p>}
          {chatError && (
            <div className="max-w-3xl mx-auto mb-3 flex items-center justify-between gap-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-500">
              <span>{chatError}</span>
              <button
                type="button"
                onClick={() => void runSearch(lastFailedQuery)}
                disabled={isSearching || !lastFailedQuery}
                className="inline-flex items-center gap-1 font-semibold hover:underline disabled:opacity-50"
              >
                <RotateCcw size={12} /> Retry answer
              </button>
            </div>
          )}
          <label className="max-w-3xl mx-auto mb-2 flex items-center gap-2 text-xs text-neutral-600 dark:text-neutral-400">
            <input type="checkbox" checked={comparisonMode} onChange={(event) => setComparisonMode(event.target.checked)} aria-label="Compare selected documents" />
            Compare selected documents (select 2–4)
          </label>
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
            {isSearching && (
              <button
                type="button"
                onClick={cancelChat}
                className="px-3 py-2.5 rounded-lg border border-red-500/40 text-red-500 text-xs hover:bg-red-500/10"
              >
                {isStopping ? "Stopping..." : "Stop generating"}
              </button>
            )}
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
          <label className={`border-2 border-dashed border-neutral-300 dark:border-neutral-800 hover:border-[#D4AF37]/50 rounded-xl p-6 flex flex-col items-center justify-center gap-2 bg-neutral-50 dark:bg-neutral-950/40 transition-all ${isIngesting ? "opacity-60 cursor-not-allowed" : "cursor-pointer"}`}>
            <UploadCloud size={20} className="text-neutral-500" />
            <span className="text-xs font-medium text-neutral-700 dark:text-neutral-300">Drop files or click to upload</span>
            <span className="text-[10px] text-neutral-500">PDF documents supported</span>
            <input
              type="file"
              accept=".pdf"
              disabled={isIngesting}
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

        {ingestStep > 0 && (
          <IngestionStepper
            currentStep={ingestStep}
            errorMsg={ingestError}
            isRunning={isIngesting}
            onCancel={cancelIngestion}
            onRetry={lastIngestFile ? () => void handleIngestStream(lastIngestFile) : undefined}
          />
        )}

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
                {selectedDocIds.size === readyDocuments.length ? "Deselect all" : "Select all"}
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
                    disabled={isDeleting || (!!doc.status && doc.status !== "ready")}
                    className="accent-[#D4AF37] cursor-pointer shrink-0"
                    aria-label={`Use ${doc.filename} as a source`}
                  />
                  <FileText size={14} className="text-[#D4AF37] shrink-0" />
                  <span className="truncate flex-1" title={doc.filename}>
                    {doc.filename}
                  </span>
                  <button type="button" onClick={() => void editDocumentTags(doc)} disabled={isDeleting || (!!doc.status && doc.status !== "ready")} className="text-[10px] text-[#D4AF37] hover:underline disabled:opacity-50" title={(doc.tags || []).join(", ") || "No tags"} aria-label={`Edit tags for ${doc.filename}`}>
                    {doc.tags?.length ? `${doc.tags.length} tags` : "Tags"}
                  </button>
                  {doc.status && doc.status !== "ready" && (
                    <span className="text-[9px] text-amber-500" title={doc.error || doc.status}>
                      {doc.status.replace("_", " ")}
                    </span>
                  )}
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
      {activePdfSource && (
        <PdfCitationViewer
          chunk={activePdfSource}
          onClose={() => setActivePdfSource(null)}
        />
      )}

      <CitationLightbox data={activeLightbox} onClose={() => setActiveLightbox(null)} />
    </div>
  );
}
