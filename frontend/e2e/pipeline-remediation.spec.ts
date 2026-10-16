import { randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";
import type { PipelineCatalog, PipelineView } from "../src/types/pipelines.generated";
import { loginWithEmail } from "./helpers/auth";

test("preserves edits made after a real atomic draft save was submitted", async ({ page }) => {
  await page.goto("/login");
  await loginWithEmail(page, process.env.SUPERUSER_MAIL ?? "admin@example.com", { rememberMe: true });
  const token = await page.evaluate(() => localStorage.getItem("auth_token"));
  expect(token).toBeTruthy();
  const headers = { Authorization: `Bearer ${token}` };
  const catalogResponse = await page.request.get("/api/v1/monitors/pipelines/catalog", { headers });
  expect(catalogResponse.ok()).toBe(true);
  const catalog = await catalogResponse.json() as PipelineCatalog;
  const created = await page.request.post("/api/v1/monitors/pipelines", {
    headers, data: { name: `Save race ${randomUUID()}`, definition: catalog.templates[0]!.definition },
  });
  expect(created.ok(), await created.text()).toBe(true);
  const design = await created.json() as PipelineView;
  const endpoint = `/api/v1/monitors/pipelines/${design.id}`;
  let release!: () => void;
  let submitted!: () => void;
  const saving = new Promise<void>(resolve => { submitted = resolve; });
  const held = new Promise<void>(resolve => { release = resolve; });
  const routePattern = `**${endpoint}/draft`;
  await page.route(routePattern, async route => {
    // Persist through the real gateway and database, then delay only delivery
    // of its response to reproduce an ordinary slow network acknowledgement.
    const response = await route.fetch();
    submitted();
    await held;
    await route.fulfill({ response });
  });
  try {
    await page.goto(`/?view=pipelines&pipeline=${encodeURIComponent(design.id)}`);
    const editor = page.getByRole("region", { name: "Pipeline editor", exact: true });
    await editor.getByRole("combobox", { name: "Selected component", exact: true }).selectOption("input");
    const title = editor.getByRole("textbox", { name: "Node title", exact: true });
    await title.fill("Submitted title");
    await editor.getByText("Name and description", { exact: true }).click();
    const name = editor.getByRole("textbox", { name: "Pipeline name", exact: true });
    await name.fill("Submitted name");
    await editor.getByRole("button", { name: "Save draft", exact: true }).click();
    await saving;
    await title.fill("New unsaved title");
    await name.fill("New unsaved name");
    release();
    await expect(editor.getByText("Draft saved.", { exact: true })).toBeVisible();
    await expect(title).toHaveValue("New unsaved title");
    await expect(name).toHaveValue("New unsaved name");
    await expect(editor.getByText("Unsaved draft changes", { exact: false })).toBeVisible();
    const saved = await page.request.get(endpoint, { headers });
    const first = await saved.json() as PipelineView;
    expect(first.version).toBe(design.version + 1);
    expect(first.name).toBe("Submitted name");
    expect(first.layout.nodes?.input?.label).toBe("Submitted title");
    await page.unroute(routePattern);
    await editor.getByRole("button", { name: "Save draft", exact: true }).click();
    await expect(editor.getByText("Saved draft", { exact: false })).toBeVisible();
    await page.reload();
    await editor.getByRole("combobox", { name: "Selected component", exact: true }).selectOption("input");
    await expect(title).toHaveValue("New unsaved title");
    await expect(editor.getByRole("heading", { name: "New unsaved name", exact: true })).toBeVisible();
  } finally {
    release();
    await page.unroute(routePattern);
    const current = await page.request.get(endpoint, { headers });
    const latest = await current.json() as PipelineView;
    const archived = await page.request.patch(endpoint, {
      headers, data: { expected_version: latest.version, name: latest.name, description: latest.description, archived: true },
    });
    expect(archived.ok(), await archived.text()).toBe(true);
  }
});
