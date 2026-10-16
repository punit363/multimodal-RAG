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
