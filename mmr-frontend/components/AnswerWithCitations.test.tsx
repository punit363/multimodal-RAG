import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AnswerWithCitations } from "@/components/AnswerWithCitations";

describe("AnswerWithCitations", () => {
  it("opens only citations bound to a returned source", () => {
    const onOpenPdf = vi.fn();
    const source = {
      chunk_id: "doc-1::2",
      document_id: "doc-1",
      filename: "report.pdf",
      page_numbers: [3],
      enhanced_content: "Revenue rose.",
      metadata: { original_content: { raw_text: "Revenue rose.", tables_html: [], images_base64: [] } },
    };
    render(
      <AnswerWithCitations
        text="Revenue rose [[source:doc-1::2]]. Unknown [[source:missing]]."
        sources={[source]}
        onOpenPdf={onOpenPdf}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "Open citation report.pdf, p.3" }));
    expect(onOpenPdf).toHaveBeenCalledWith(source);
    expect(screen.getByText("[Unverified source]")).toBeVisible();
    expect(screen.queryByRole("button", { name: /missing/ })).not.toBeInTheDocument();
  });

  it("labels a source whose page is unknown without inventing a page", () => {
    const onOpenPdf = vi.fn();
    const source = {
      chunk_id: "doc-2::0",
      document_id: "doc-2",
      filename: "appendix.pdf",
      page_numbers: [],
      enhanced_content: "Appendix",
      metadata: { original_content: { raw_text: "Appendix", tables_html: [], images_base64: [] } },
    };
    render(<AnswerWithCitations text="See [[source:doc-2::0]]" sources={[source]} onOpenPdf={onOpenPdf} />);
    fireEvent.click(screen.getByRole("button", { name: "Open citation appendix.pdf, page unavailable" }));
    expect(onOpenPdf).toHaveBeenCalledWith(source);
  });

  it("renders Markdown while blocking active HTML and unsafe links", () => {
    const onOpenPdf = vi.fn();
    const source = {
      chunk_id: "doc-1::2", document_id: "doc-1", filename: "report.pdf", page_numbers: [3],
      enhanced_content: "Claim", metadata: { original_content: { raw_text: "Claim", tables_html: [], images_base64: [] } },
    };
    const { container } = render(<AnswerWithCitations
      text={'**Claim [[source:doc-1::2]]**\n\n```js\n[[source:doc-1::2]]\n```\n\n[Safe](https://example.com) [Unsafe](javascript:alert(1)) <img src=x onerror=alert(1)>'}
      sources={[source]} onOpenPdf={onOpenPdf} />);
    const answer = within(container);
    expect(answer.getByRole("button", { name: "Open citation report.pdf, p.3" }).closest("strong")).toBeTruthy();
    expect(answer.getByText("[[source:doc-1::2]]", { selector: "code" })).toBeVisible();
    expect(answer.getByRole("link", { name: "Safe" })).toHaveAttribute("href", "https://example.com");
    expect(answer.queryByRole("link", { name: "Unsafe" })).not.toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
  });
});
