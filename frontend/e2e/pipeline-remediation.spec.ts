import { randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";
import type { PipelineCatalog, PipelineView } from "../src/types/pipelines.generated";
import { loginPipelineWorkspace } from "./helpers/pipelines";
import { openPipelineSettings, savePipelineTemplate } from "./helpers/pipelineNavigation";
import { accessToken } from "./helpers/auth";

test("preserves edits made after a real atomic draft save was submitted", async ({ page }) => {
  await loginPipelineWorkspace(page);
  const token = await accessToken(page);
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
    await openPipelineSettings(editor, "Component");
    await editor.getByRole("combobox", { name: "Selected component", exact: true }).selectOption("input");
    const title = editor.getByRole("textbox", { name: "Node title", exact: true });
    await title.fill("Submitted title");
    await openPipelineSettings(editor, "Service");
    const name = editor.getByRole("textbox", { name: "Service name", exact: true });
    await name.fill("Submitted name");
    await editor.getByRole("button", { name: "Save template", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Save monitoring template", exact: true });
    await dialog.getByRole("textbox", { name: "Template name", exact: true }).fill("Submitted name");
    await dialog.getByRole("button", { name: "Update template", exact: true }).click();
    await saving;
    await dialog.getByRole("button", { name: "Close save template", exact: true }).click();
    await openPipelineSettings(editor, "Component");
    await title.fill("New unsaved title");
    await openPipelineSettings(editor, "Service");
    await name.fill("New unsaved name");
    release();
    await expect(page.getByRole("status").filter({ hasText: /Template saved/ })).toBeVisible();
    await openPipelineSettings(editor, "Component");
    await expect(title).toHaveValue("New unsaved title");
    await openPipelineSettings(editor, "Service");
    await expect(name).toHaveValue("New unsaved name");

    const saved = await page.request.get(endpoint, { headers });
    const first = await saved.json() as PipelineView;
    expect(first.version).toBe(design.version + 1);
    expect(first.name).toBe("Submitted name");
    expect(first.layout.nodes?.input?.label).toBe("Submitted title");
    await page.unroute(routePattern);
    await savePipelineTemplate(page, "Updated template");
    await page.reload();
    await openPipelineSettings(editor, "Component");
    await editor.getByRole("combobox", { name: "Selected component", exact: true }).selectOption("input");
    await expect(title).toHaveValue("New unsaved title");
    await expect(name).toHaveValue("New unsaved name");
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
