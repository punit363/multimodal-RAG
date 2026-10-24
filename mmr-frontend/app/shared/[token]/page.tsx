"use client";

import { Suspense, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { API_BASE_URL, fetchWithTimeout } from "@/lib/api";

interface SharedPage {
  resource_type: "collection" | "conversation";
  permission: "view" | "comment";
  expires_at: string;
  resource: {
    name?: string;
    title?: string;
    documents?: { id: string; filename: string; tags: string[] }[];
    summary?: { items: { text: string; chunk_id: string; filename: string }[] };
    messages?: { id: string; role: string; content: string; sources?: { chunk_id: string; filename: string }[] }[];
  };
  comments: { id: string; author: string; body: string }[];
}

function SharedView() {
  const { token } = useParams<{ token: string }>();
  const [data, setData] = useState<SharedPage | null>(null);
  const [error, setError] = useState("");
  const [author, setAuthor] = useState("");
  const [body, setBody] = useState("");
  const [sending, setSending] = useState(false);

  useEffect(() => {
    if (!token) return;
    void fetchWithTimeout(`${API_BASE_URL}/api/public-shares/${encodeURIComponent(token)}`).then(async (response) => {
      if (!response.ok) throw new Error("This share link has expired or been revoked.");
      setData(await response.json());
    }).catch((reason) => setError(reason instanceof Error ? reason.message : "Could not load shared content."));
  }, [token]);

  const postComment = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!data || data.permission !== "comment" || sending) return;
    setSending(true);
    setError("");
    try {
      const response = await fetchWithTimeout(`${API_BASE_URL}/api/public-shares/${encodeURIComponent(token)}/comments`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ author, body }),
      });
      if (!response.ok) throw new Error("Could not post comment. The link may have expired.");
      const comment = await response.json();
      setData({ ...data, comments: [...data.comments, comment] });
      setBody("");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not post comment."); }
    finally { setSending(false); }
  };

  return <main className="min-h-screen bg-neutral-950 text-neutral-100 px-5 py-10"><div className="max-w-3xl mx-auto space-y-6">
    <header><p className="text-xs uppercase tracking-widest text-[#D4AF37]">MultiModal RAG · Shared {data?.resource_type || "resource"}</p><h1 className="mt-2 text-2xl font-semibold">{data?.resource.name || data?.resource.title || "Shared workspace"}</h1>{data && <p className="text-xs text-neutral-400">{data.permission === "comment" ? "Comments enabled" : "View only"} · Expires {data.expires_at.slice(0, 10)}</p>}</header>
    {error && <p role="alert" className="rounded border border-red-500/40 p-3 text-red-400">{error}</p>}
    {!data && !error && <p>Loading shared content…</p>}
    {data?.resource.documents?.map((document) => <section key={document.id} className="rounded border border-neutral-700 p-4"><h2 className="font-medium">{document.filename}</h2>{document.tags?.length > 0 && <p className="text-xs text-neutral-400">{document.tags.join(", ")}</p>}</section>)}
    {data?.resource.summary?.items?.map((item) => <blockquote key={item.chunk_id} className="border-l-2 border-[#D4AF37] pl-3 text-sm"><p>{item.text}</p><cite className="text-xs text-neutral-400">{item.filename} · {item.chunk_id}</cite></blockquote>)}
    {data?.resource.messages?.map((message) => <section key={message.id} className="rounded border border-neutral-700 p-4"><h2 className="text-xs uppercase text-[#D4AF37]">{message.role}</h2><p className="mt-2 whitespace-pre-wrap text-sm">{message.content}</p>{message.sources?.length ? <p className="mt-2 text-xs text-neutral-400">Sources: {message.sources.map((source) => `${source.filename} (${source.chunk_id})`).join(", ")}</p> : null}</section>)}
    {data && <section className="border-t border-neutral-700 pt-4 space-y-3"><h2 className="font-medium">Comments</h2>{data.comments.map((comment) => <p key={comment.id} className="text-sm"><strong>{comment.author}:</strong> {comment.body}</p>)}{data.permission === "comment" && <form onSubmit={(event) => void postComment(event)} className="space-y-2"><input aria-label="Your name" required maxLength={80} value={author} onChange={(event) => setAuthor(event.target.value)} className="w-full rounded bg-neutral-900 border border-neutral-700 p-2" placeholder="Your name" /><textarea aria-label="Comment" required maxLength={1000} value={body} onChange={(event) => setBody(event.target.value)} className="w-full rounded bg-neutral-900 border border-neutral-700 p-2" placeholder="Write a comment" /><button disabled={sending} className="rounded bg-[#D4AF37] px-3 py-2 text-black disabled:opacity-50">Post comment</button></form>}</section>}
  </div></main>;
}

export default function SharedPageRoute() {
  return <Suspense fallback={<main className="p-8">Loading shared content…</main>}><SharedView /></Suspense>;
}
