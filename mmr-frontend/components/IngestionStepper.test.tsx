import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { IngestionStepper } from "@/components/IngestionStepper";

describe("IngestionStepper", () => {
  it("shows completed, active, pending, and error states", () => {
    render(<IngestionStepper currentStep={3} errorMsg="Vision extraction failed" />);

    expect(screen.getByText("Partitioning PDF Layout")).toHaveClass("font-medium");
    expect(screen.getByText("Generating Multi-Modal Summaries")).toHaveClass("font-semibold");
    expect(screen.getByText("Persisting ChromaDB Embeddings")).toHaveClass("text-neutral-500");
    expect(screen.getByText("Vision extraction failed")).toBeVisible();
  });

  it("offers cancellation while running and retry after failure", () => {
    const onCancel = vi.fn();
    const onRetry = vi.fn();
    const { rerender } = render(
      <IngestionStepper currentStep={2} isRunning onCancel={onCancel} />
    );

    fireEvent.click(screen.getByRole("button", { name: "Cancel ingestion" }));
    expect(onCancel).toHaveBeenCalledOnce();

    rerender(
      <IngestionStepper currentStep={2} errorMsg="Upload failed" onRetry={onRetry} />
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry upload" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
