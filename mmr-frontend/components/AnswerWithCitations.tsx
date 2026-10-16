import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Root, RootContent, PhrasingContent } from "mdast";
import { RetrievedChunk } from "@/types/rag";

interface AnswerWithCitationsProps {
  text: string;
  sources: RetrievedChunk[];
  onOpenPdf: (chunk: RetrievedChunk) => void;
}

const citationPattern = /\[\[source:([^\]]+)\]\]/g;

function remarkCitationLinks() {
  return (tree: Root) => {
    function transform(node: Root | RootContent) {
      if (!("children" in node)) return;
      const children = node.children as PhrasingContent[];
      for (let index = 0; index < children.length; index += 1) {
        const child = children[index];
        if (child.type !== "text") {
          transform(child);
          continue;
        }
        const parts: PhrasingContent[] = [];
        let start = 0;
        for (const match of child.value.matchAll(citationPattern)) {
          if (match.index > start) parts.push({ type: "text", value: child.value.slice(start, match.index) });
          parts.push({ type: "link", url: `citation:${encodeURIComponent(match[1])}`, children: [{ type: "text", value: match[0] }] });
          start = match.index + match[0].length;
        }
        if (!parts.length) continue;
        if (start < child.value.length) parts.push({ type: "text", value: child.value.slice(start) });
        children.splice(index, 1, ...parts);
        index += parts.length - 1;
      }
    }
    transform(tree);
  };
}

function safeUrl(url: string): string {
  if (url.startsWith("citation:")) return url;
  try {
    const parsed = new URL(url);
    return ["https:", "http:", "mailto:"].includes(parsed.protocol) ? url : "";
  } catch {
    return "";
  }
}

export function AnswerWithCitations({ text, sources, onOpenPdf }: AnswerWithCitationsProps) {
  return (
    <div className="space-y-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_ul]:list-disc [&_ul]:pl-5 [&_blockquote]:border-l-2 [&_blockquote]:border-amber-500 [&_blockquote]:pl-3">
      <Markdown
        skipHtml
        remarkPlugins={[remarkGfm, remarkCitationLinks]}
        urlTransform={safeUrl}
        components={{
          a({ href, children }) {
            if (href?.startsWith("citation:")) {
              let chunkId = "";
              try { chunkId = decodeURIComponent(href.slice("citation:".length)); } catch { /* unmatched marker */ }
              const source = sources.find((chunk) => String(chunk.chunk_id) === chunkId);
              if (!source?.document_id) {
                return <span title="This citation does not match an available PDF source" className="text-amber-600 dark:text-amber-400">[Unverified source]</span>;
              }
              const page = source.page_numbers?.[0];
              const label = `${source.filename || "Document"}, ${page ? `p.${page}` : "page unavailable"}`;
              return <button type="button" onClick={() => onOpenPdf(source)} aria-label={`Open citation ${label}`}
                className="mx-1 rounded border border-amber-500/40 px-1 text-[#D4AF37] hover:bg-amber-500/10">[{label}]</button>;
            }
            if (!href) return <span>{children}</span>;
            return <a href={href} target="_blank" rel="noopener noreferrer" className="text-[#D4AF37] underline">{children}</a>;
          },
          code({ children, className }) {
            return <code className={`rounded bg-neutral-200 px-1 py-0.5 font-mono dark:bg-neutral-800 ${className || ""}`}>{children}</code>;
          },
          pre({ children }) {
            return <pre className="overflow-x-auto rounded-lg bg-neutral-200 p-3 dark:bg-neutral-950">{children}</pre>;
          },
        }}
      >{text}</Markdown>
    </div>
  );
}
