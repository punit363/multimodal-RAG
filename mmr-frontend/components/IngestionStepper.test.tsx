import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { IngestionStepper } from "@/components/IngestionStepper";

describe("IngestionStepper", () => {
  it("shows completed, active, pending, and error states", () => {
    render(<IngestionStepper currentStep={3} errorMsg="Vision extraction failed" />);

    expect(screen.getByText("Partitioning PDF Layout")).toHaveClass("font-medium");
    expect(screen.getByText("Generating Multi-Modal Summaries")).toHaveClass("font-semibold");
    expect(screen.getByText("Persisting ChromaDB Embeddings")).toHaveClass("text-neutral-500");
    expect(screen.getByText("Vision extraction failed")).toBeVisible();
  });
});
