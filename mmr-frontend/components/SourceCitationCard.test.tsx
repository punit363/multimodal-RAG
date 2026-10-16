import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SourceCitationCard } from "@/components/SourceCitationCard";

describe("SourceCitationCard", () => {
  it("renders source content and opens an extracted table", () => {
    const onOpenLightbox = vi.fn();
    render(
      <SourceCitationCard
        chunk={{
          chunk_id: 4,
          enhanced_content: "Quarterly results",
          metadata: {
            original_content: {
              raw_text: "Revenue increased by 12%.",
              tables_html: ["<table><tbody><tr><td>Revenue</td><td>12%</td></tr></tbody></table>"],
              images_base64: [],
            },
          },
        }}
        onOpenLightbox={onOpenLightbox}
      />
    );

    expect(screen.getByText("Chunk #4")).toBeVisible();
    expect(screen.getByText("Revenue increased by 12%.")).toBeVisible();

    fireEvent.click(screen.getByText("Revenue"));
    expect(onOpenLightbox).toHaveBeenCalledWith({
      type: "table",
      content: "<table><tbody><tr><td>Revenue</td><td>12%</td></tr></tbody></table>",
      chunkId: 4,
    });
  });

  it("labels weak retrieval similarity without calling it confidence", () => {
    render(<SourceCitationCard chunk={{
      chunk_id: "doc::1", relevance_score: 0.42, enhanced_content: "Excerpt",
      metadata: { original_content: { raw_text: "Excerpt", tables_html: [], images_base64: [] } },
    }} />);
    expect(screen.getByText("42% retrieval similarity · Weak match")).toBeVisible();
    expect(screen.getByTitle(/not the probability/)).toBeVisible();
  });
});
