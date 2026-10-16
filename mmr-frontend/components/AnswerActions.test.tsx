import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AnswerActions, answerExportMarkdown } from "@/components/AnswerActions";

afterEach(() => vi.unstubAllGlobals());

describe("AnswerActions", () => {
  it("copies, exports, and regenerates a saved answer", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    const createObjectURL = vi.fn().mockReturnValue("blob:answer");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const onRegenerate = vi.fn();
    render(<AnswerActions answer="**Revenue rose.**" messageId="answer-1" sources={[]} onRegenerate={onRegenerate} />);
    fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("**Revenue rose.**"));
    fireEvent.click(screen.getByRole("button", { name: "Export" }));
    expect(createObjectURL).toHaveBeenCalled();
    await waitFor(() => expect(revokeObjectURL).toHaveBeenCalledWith("blob:answer"));
    fireEvent.click(screen.getByRole("button", { name: "Regenerate" }));
    expect(onRegenerate).toHaveBeenCalledOnce();
  });

  it("shows the stop state and exports honest source locations", () => {
    const onStop = vi.fn();
    render(<AnswerActions answer="Partial" messageId="answer-2" sources={[]} isGenerating onStop={onStop} />);
    fireEvent.click(screen.getByRole("button", { name: "Stop generating" }));
    expect(onStop).toHaveBeenCalledOnce();
    expect(answerExportMarkdown("Answer", [{ chunk_id: "doc::1", filename: "report.pdf", page_numbers: [], enhanced_content: "", metadata: { original_content: { raw_text: "", tables_html: [], images_base64: [] } } }])).toContain("report.pdf (page unavailable; source doc::1)");
  });
});
