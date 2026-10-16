import { expect, test } from "@playwright/test";

function twoPagePdf(): Buffer {
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] /Contents 4 0 R >>",
    "<< /Length 0 >>\nstream\n\nendstream",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] /Contents 6 0 R >>",
    "<< /Length 0 >>\nstream\n\nendstream",
  ];
  let pdf = "%PDF-1.4\n";
  const offsets = [0];
  for (const [index, object] of objects.entries()) {
    offsets.push(Buffer.byteLength(pdf));
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`;
  }
  const xrefOffset = Buffer.byteLength(pdf);
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  for (const offset of offsets.slice(1)) {
    pdf += `${String(offset).padStart(10, "0")} 00000 n \n`;
  }
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF`;
  return Buffer.from(pdf);
}

test("opens an inline citation at its PDF page with a real highlight", async ({ page }) => {
  let pdfRequests = 0;
  await page.route("http://localhost:8000/api/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    const method = route.request().method();
    if (pathname === "/api/conversations" && method === "GET") return route.fulfill({ json: [] });
    if (pathname === "/api/documents" && method === "GET") {
      return route.fulfill({ json: [{ id: "doc-1", filename: "report.pdf", status: "ready" }] });
    }
    if (pathname === "/api/conversations" && method === "POST") {
      return route.fulfill({ json: { id: "conversation-1", title: "Revenue", messages: [] } });
    }
    if (pathname === "/api/documents/doc-1/pdf") {
      pdfRequests += 1;
      return route.fulfill({
        body: twoPagePdf(),
        headers: { "Content-Type": "application/pdf" },
      });
    }
    if (pathname === "/api/chat-stream") {
      const source = {
        chunk_id: "doc-1::0",
        document_id: "doc-1",
        filename: "report.pdf",
        page_numbers: [2],
        highlight_rect: { page: 2, left: 0.1, top: 0.2, width: 0.3, height: 0.1 },
        metadata: { original_content: { raw_text: "Revenue rose.", tables_html: [], images_base64: [] } },
      };
      return route.fulfill({
        contentType: "text/event-stream",
        body: [
          `data: ${JSON.stringify({ type: "sources", sources: [source] })}\n\n`,
          `data: ${JSON.stringify({ type: "token", token: "Revenue rose [[source:doc-1::0]]" })}\n\n`,
          `data: ${JSON.stringify({ type: "done" })}\n\n`,
        ].join(""),
      });
    }
    return route.abort();
  });

  await page.goto("/chat");
  const question = page.getByPlaceholder("Ask a question about your selected documents...");
  await question.fill("What happened to revenue?");
  await question.press("Enter");
  await page.getByRole("button", { name: "Open citation report.pdf, p.2" }).click();
  const viewer = page.getByRole("dialog", { name: "PDF source: report.pdf" });
  await expect(viewer.getByText("Page 2 of 2")).toBeVisible();
  await expect(viewer.getByLabel("Cited content highlight")).toBeVisible();
  expect(pdfRequests).toBeGreaterThan(0);
});

test("shows an explicit insufficient-evidence answer without sources", async ({ page }) => {
  await page.route("http://localhost:8000/api/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    const method = route.request().method();
    if (pathname === "/api/conversations" && method === "GET") return route.fulfill({ json: [] });
    if (pathname === "/api/documents" && method === "GET") {
      return route.fulfill({ json: [{ id: "doc-1", filename: "report.pdf", status: "ready" }] });
    }
    if (pathname === "/api/conversations" && method === "POST") {
      return route.fulfill({ json: { id: "conversation-1", title: "Unknown", messages: [] } });
    }
    if (pathname === "/api/chat-stream") {
      return route.fulfill({
        contentType: "text/event-stream",
        body: [
          `data: ${JSON.stringify({ type: "sources", sources: [] })}\n\n`,
          `data: ${JSON.stringify({ type: "token", token: "I don't have enough relevant evidence in the selected documents to answer that question." })}\n\n`,
          `data: ${JSON.stringify({ type: "done", insufficient_evidence: true })}\n\n`,
        ].join(""),
      });
    }
    return route.abort();
  });

  await page.goto("/chat");
  const question = page.getByPlaceholder("Ask a question about your selected documents...");
  await question.fill("What is the moon made of?");
  await question.press("Enter");
  await expect(page.getByText(/don't have enough relevant evidence/)).toBeVisible();
  await expect(page.getByText("Retrieved Sources")).toHaveCount(0);
});

test("saves answer feedback and restores it after reloading", async ({ page }) => {
  let feedback: "helpful" | "not_helpful" | null = null;
  await page.route("http://localhost:8000/api/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === "/api/documents") return route.fulfill({ json: [] });
    if (pathname === "/api/conversations") {
      return route.fulfill({ json: [{ id: "conversation-1", title: "Revenue", messages: [
        { id: "answer-1", role: "assistant", content: "Revenue rose.", sources: [], feedback },
      ] }] });
    }
    if (pathname === "/api/messages/answer-1/feedback" && route.request().method() === "PATCH") {
      feedback = route.request().postDataJSON().feedback;
      return route.fulfill({ json: { message_id: "answer-1", feedback } });
    }
    return route.abort();
  });
  await page.goto("/chat");
  const helpful = page.getByRole("button", { name: "Helpful answer", exact: true });
  await helpful.click();
  await expect(helpful).toHaveAttribute("aria-pressed", "true");
  await page.reload();
  await expect(page.getByRole("button", { name: "Helpful answer", exact: true })).toHaveAttribute("aria-pressed", "true");
});
