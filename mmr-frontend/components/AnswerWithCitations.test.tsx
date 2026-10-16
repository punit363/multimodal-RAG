import { fireEvent, render, screen } from "@testing-library/react";
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
    expect(screen.getByText(/Unknown \[\[source:missing\]\]/)).toBeVisible();
  });
});
