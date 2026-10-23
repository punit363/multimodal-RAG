import path from "node:path";
import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";

test("loads documents and streams a cited answer", async ({ page }) => {
  await page.route("http://localhost:8000/api/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;

    if (pathname === "/api/conversations" && request.method() === "GET") {
      await route.fulfill({ json: [] });
      return;
    }
    if (pathname === "/api/documents" && request.method() === "GET") {
      await route.fulfill({ json: [{ id: "doc-1", filename: "report.pdf" }] });
      return;
    }
    if (pathname === "/api/conversations" && request.method() === "POST") {
      await route.fulfill({
        json: { id: "conversation-1", title: "What changed?", messages: [] },
      });
      return;
    }
    if (pathname === "/api/chat-stream" && request.method() === "POST") {
      const body = request.postDataJSON();
      expect(body.sources).toEqual(["doc-1"]);
      await route.fulfill({
        contentType: "text/event-stream",
        body: [
          `data: ${JSON.stringify({
            type: "sources",
            sources: [
              {
                chunk_id: 1,
                enhanced_content: "Revenue increased.",
                metadata: {
                  original_content: {
                    raw_text: "Revenue increased by 12%.",
                    tables_html: [],
                    images_base64: [],
                  },
                },
              },
            ],
          })}\n\n`,
          `data: ${JSON.stringify({ type: "token", token: "Revenue increased by 12%." })}\n\n`,
          `data: ${JSON.stringify({ type: "done" })}\n\n`,
        ].join(""),
      });
      return;
    }

    await route.abort();
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Multi-Modal RAG/i })).toBeVisible();
  await page.screenshot({
    path: path.resolve("../docs/images/landing-page.png"),
    fullPage: true,
  });

  await page.goto("/chat");
  await expect(page.getByLabel("Use report.pdf as a source")).toBeChecked();
  const question = page.getByPlaceholder("Ask a question about your selected documents...");
  await question.fill("What changed?");
  await question.press("Enter");

  await expect(page.getByText("Revenue increased by 12%.", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Retrieved Sources (1)")).toBeVisible();
  await expect(page.getByRole("button", { name: "Copy" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Export" })).toBeVisible();
  await page.screenshot({
    path: path.resolve("../docs/images/chat-workspace.png"),
    fullPage: true,
  });
});

test("passes page, content, date and tag filters with selected documents", async ({ page }) => {
  let requestBody: Record<string, unknown> | null = null;
  await page.route("http://localhost:8000/api/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === "/api/conversations" && route.request().method() === "GET") return route.fulfill({ json: [] });
    if (pathname === "/api/conversations" && route.request().method() === "POST") return route.fulfill({ json: { id: "conv-1", title: "Filtered", messages: [] } });
    if (pathname === "/api/documents") return route.fulfill({ json: [{ id: "doc-1", filename: "report.pdf", status: "ready", tags: ["Finance"] }] });
    if (pathname === "/api/chat-stream") {
      requestBody = route.request().postDataJSON();
      return route.fulfill({ contentType: "text/event-stream", body: `data: ${JSON.stringify({ type: "done" })}\n\n` });
    }
    return route.abort();
  });
  await page.goto("/chat");
  await expect(page.getByLabel("Use report.pdf as a source")).toBeChecked();
  await page.getByLabel("Filter by page").fill("3");
  await page.getByLabel("Filter by content type").selectOption("table");
  await page.getByLabel("Filter from date").fill("2026-01-01");
  await page.getByLabel("Filter through date").fill("2026-12-31");
  await page.getByLabel("Filter by tag").selectOption("Finance");
  const question = page.getByPlaceholder("Ask a question about your selected documents...");
  await question.fill("What changed?");
  await question.press("Enter");
  await expect.poll(() => requestBody).not.toBeNull();
  expect(requestBody).toMatchObject({
    sources: ["doc-1"],
    filters: {
      pages: [3], content_types: ["table"], created_from: "2026-01-01",
      created_to: "2026-12-31", tags: ["Finance"],
    },
  });
});

test("comparison mode requires two sources and sends both document IDs", async ({ page }) => {
  let requestBody: Record<string, unknown> | null = null;
  await page.route("http://localhost:8000/api/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === "/api/conversations" && route.request().method() === "GET") return route.fulfill({ json: [] });
    if (pathname === "/api/conversations" && route.request().method() === "POST") return route.fulfill({ json: { id: "conv-compare", title: "Compare", messages: [] } });
    if (pathname === "/api/documents") return route.fulfill({ json: [
      { id: "doc-a", filename: "alpha.pdf", status: "ready" },
      { id: "doc-b", filename: "beta.pdf", status: "ready" },
    ] });
    if (pathname === "/api/chat-stream") {
      requestBody = route.request().postDataJSON();
      return route.fulfill({ contentType: "text/event-stream", body: `data: ${JSON.stringify({ type: "done" })}\n\n` });
    }
    return route.abort();
  });
  await page.goto("/chat");
  await page.getByLabel("Compare selected documents").check();
  await page.getByLabel("Use beta.pdf as a source").uncheck();
  const question = page.getByPlaceholder("Ask a question about your selected documents...");
  await question.fill("Compare revenue");
  await question.press("Enter");
  await expect(page.getByText("Select two to four ready documents for comparison.")).toBeVisible();
  expect(requestBody).toBeNull();
  await page.getByLabel("Use beta.pdf as a source").check();
  await question.press("Enter");
  await expect.poll(() => requestBody).not.toBeNull();
  expect(requestBody).toMatchObject({ mode: "compare", sources: ["doc-a", "doc-b"] });
});

test("saves, reloads, updates, and deletes a source set", async ({ page }) => {
  let saved: { id: string; name: string; document_ids: string[] }[] = [];
  await page.route("http://localhost:8000/api/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    const method = route.request().method();
    if (pathname === "/api/conversations") return route.fulfill({ json: [] });
    if (pathname === "/api/documents") return route.fulfill({ json: [
      { id: "doc-a", filename: "alpha.pdf", status: "ready" },
      { id: "doc-b", filename: "beta.pdf", status: "ready" },
    ] });
    if (pathname === "/api/source-sets" && method === "GET") return route.fulfill({ json: saved });
    if (pathname === "/api/source-sets" && method === "POST") {
      saved = [{ id: "set-1", ...route.request().postDataJSON() }];
      return route.fulfill({ json: saved[0] });
    }
    if (pathname === "/api/source-sets/set-1" && method === "PUT") {
      saved = [{ id: "set-1", ...route.request().postDataJSON() }];
      return route.fulfill({ json: saved[0] });
    }
    if (pathname === "/api/source-sets/set-1" && method === "DELETE") {
      saved = [];
      return route.fulfill({ json: { status: "deleted", id: "set-1" } });
    }
    return route.abort();
  });
  page.on("dialog", (dialog) => void dialog.accept("Research"));
  await page.goto("/chat");
  await expect(page.getByLabel("Use alpha.pdf as a source")).toBeChecked();
  await page.getByRole("button", { name: "Save selection" }).click();
  await expect(page.getByLabel("Saved source sets")).toHaveValue("set-1");
  await page.getByLabel("Use beta.pdf as a source").uncheck();
  await page.getByRole("button", { name: "Update set" }).click();
  await expect.poll(() => saved[0].document_ids).toEqual(["doc-a"]);
  await page.reload();
  await page.getByLabel("Saved source sets").selectOption("set-1");
  await expect(page.getByLabel("Use alpha.pdf as a source")).toBeChecked();
  await expect(page.getByLabel("Use beta.pdf as a source")).not.toBeChecked();
  await page.getByRole("button", { name: "Delete set" }).click();
  await expect(page.getByLabel("Saved source sets").locator("option[value='set-1']")).toHaveCount(0);
});

test("batch upload continues after failure and retries only that file", async ({ page }) => {
  const attempts: Record<string, number> = {};
  await page.route("http://localhost:8000/api/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === "/api/conversations" || pathname === "/api/documents" || pathname === "/api/source-sets") {
      return route.fulfill({ json: [] });
    }
    if (pathname === "/api/ingest-stream") {
      const body = route.request().postDataBuffer()?.toString() || "";
      const filename = body.includes("first.pdf") ? "first.pdf" : "second.pdf";
      attempts[filename] = (attempts[filename] || 0) + 1;
      const failed = filename === "first.pdf" && attempts[filename] === 1;
      const event = failed
        ? { step: -1, status: "error", label: "First file failed" }
        : { step: 5, status: "completed", filename, document_id: filename };
      return route.fulfill({ contentType: "text/event-stream", body: `data: ${JSON.stringify(event)}\n\n` });
    }
    return route.abort();
  });
  await page.goto("/chat");
  await page.locator('input[type="file"]').setInputFiles([
    { name: "first.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-first") },
    { name: "second.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-second") },
  ]);
  await expect(page.getByLabel("Upload batch").getByText("first.pdf")).toBeVisible();
  await expect(page.getByLabel("Upload batch").getByText("second.pdf")).toBeVisible();
  await expect.poll(() => attempts["second.pdf"]).toBe(1);
  await expect(page.getByLabel("Upload batch").getByText("failed")).toBeVisible();
  await expect(page.getByLabel("Upload batch").getByText("completed")).toBeVisible();
  await page.getByLabel("Upload batch").getByRole("button", { name: "Retry" }).click();
  await expect.poll(() => attempts["first.pdf"]).toBe(2);
  await expect(page.getByLabel("Upload batch").getByText("completed")).toHaveCount(2);
});

test("edits document tags and offers the new tag as a filter", async ({ page }) => {
  let tags: string[] = [];
  await page.route("http://localhost:8000/api/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === "/api/conversations") return route.fulfill({ json: [] });
    if (pathname === "/api/documents" && route.request().method() === "GET") {
      return route.fulfill({ json: [{ id: "doc-1", filename: "report.pdf", status: "ready", tags }] });
    }
    if (pathname === "/api/documents/doc-1/tags" && route.request().method() === "PATCH") {
      tags = route.request().postDataJSON().tags;
      return route.fulfill({ json: { id: "doc-1", filename: "report.pdf", status: "ready", tags } });
    }
    return route.abort();
  });
  page.on("dialog", (dialog) => void dialog.accept("Finance, 2026"));
  await page.goto("/chat");
  await page.getByRole("button", { name: "Edit tags for report.pdf" }).click();
  await expect(page.getByRole("button", { name: "Edit tags for report.pdf" })).toHaveText("2 tags");
  await expect(page.getByLabel("Filter by tag").locator("option[value='Finance']")).toHaveCount(1);
  expect(tags).toEqual(["Finance", "2026"]);
});

test("shows a retry action after a streamed answer fails", async ({ page }) => {
  let chatAttempts = 0;
  await page.route("http://localhost:8000/api/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;

    if (pathname === "/api/conversations" && request.method() === "GET") {
      await route.fulfill({ json: [] });
      return;
    }
    if (pathname === "/api/documents" && request.method() === "GET") {
      await route.fulfill({ json: [{ id: "doc-1", filename: "report.pdf", status: "ready" }] });
      return;
    }
    if (pathname === "/api/conversations" && request.method() === "POST") {
      await route.fulfill({ json: { id: "conversation-1", title: "Retry", messages: [] } });
      return;
    }
    if (pathname === "/api/chat-stream") {
      chatAttempts += 1;
      await route.fulfill({
        contentType: "text/event-stream",
        body:
          chatAttempts === 1
            ? `data: ${JSON.stringify({ type: "error", message: "Temporary model failure" })}\n\n`
            : `data: ${JSON.stringify({ type: "token", token: "Recovered answer" })}\n\n`,
      });
      return;
    }
    await route.abort();
  });

  await page.goto("/chat");
  const question = page.getByPlaceholder("Ask a question about your selected documents...");
  await question.fill("Can this recover?");
  await question.press("Enter");
  await expect(page.getByText("Temporary model failure", { exact: true }).first()).toBeVisible();

  await page.getByRole("button", { name: "Retry answer" }).click();
  await expect(page.getByText(/Recovered answer/).last()).toBeVisible();
  expect(chatAttempts).toBe(2);
});

test("exports and regenerates a reloaded Markdown answer", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  let regeneratedQuery = "";
  await page.route("http://localhost:8000/api/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === "/api/conversations" && route.request().method() === "GET") {
      return route.fulfill({ json: [{ id: "conversation-1", title: "Revenue", messages: [
        { id: "question-1", role: "user", content: "What changed?" },
        { id: "answer-1", role: "assistant", content: "**Revenue rose.**", sources: [] },
      ] }] });
    }
    if (pathname === "/api/documents") return route.fulfill({ json: [{ id: "doc-1", filename: "report.pdf", status: "ready" }] });
    if (pathname === "/api/chat-stream") {
      regeneratedQuery = route.request().postDataJSON().query;
      return route.fulfill({ contentType: "text/event-stream", body: [
        `data: ${JSON.stringify({ type: "sources", sources: [] })}\n\n`,
        `data: ${JSON.stringify({ type: "token", token: "Updated **answer**" })}\n\n`,
        `data: ${JSON.stringify({ type: "done" })}\n\n`,
      ].join("") });
    }
    return route.abort();
  });

  await page.goto("/chat");
  await expect(page.getByText("Revenue rose.", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Copy" }).click();
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe("**Revenue rose.**");
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("answer-answer-1.md");
  expect(await readFile(await download.path(), "utf8")).toContain("**Revenue rose.**");
  await page.getByRole("button", { name: "Regenerate" }).click();
  await expect(page.getByText("Updated", { exact: false }).last()).toBeVisible();
  expect(regeneratedQuery).toBe("What changed?");
});
