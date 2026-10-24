import { expect, test } from "@playwright/test";

test("comment-permission share displays content and accepts a comment", async ({ page }) => {
  await page.route("http://localhost:8000/api/public-shares/**", async (route) => {
    if (route.request().method() === "POST") return route.fulfill({ json: { id: "comment-1", author: "Reader", body: "Check page two" } });
    return route.fulfill({ json: { resource_type: "collection", permission: "comment", expires_at: "2026-11-01T00:00:00+00:00",
      resource: { name: "Research", documents: [{ id: "doc-1", filename: "report.pdf", tags: ["Finance"] }], summary: { items: [{ text: "Revenue rose.", chunk_id: "doc-1::1", filename: "report.pdf" }] } }, comments: [] } });
  });
  await page.goto("/shared/sample-secret");
  await expect(page.getByRole("heading", { name: "Research" })).toBeVisible();
  await expect(page.getByText("Revenue rose.")).toBeVisible();
  await page.getByLabel("Your name").fill("Reader");
  await page.getByLabel("Comment").fill("Check page two");
  await page.getByRole("button", { name: "Post comment" }).click();
  await expect(page.getByText("Check page two")).toBeVisible();
});
