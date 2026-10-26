import { randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";
import type { PipelineCatalog, PipelineView } from "../src/types/pipelines.generated";
import { addTestCharger, fixtureEntityId, removeTestCharger } from "./helpers/collection";
import { archivePipelines, openPipelineWorkspace } from "./helpers/pipelines";
import { openPipelineSettings, savePipelineTemplate } from "./helpers/pipelineNavigation";
import { accessToken } from "./helpers/auth";
import { setAppearance } from "./helpers/appearance";
import { expectNoHorizontalScroll } from "./helpers/layout";

test("selects only AC1 and AC3 and preserves named template mappings on desktop and mobile", async ({ page }, testInfo) => {
  await openPipelineWorkspace(page);
  const token = (await accessToken(page))!;
  const headers = { Authorization: `Bearer ${token}` };
  const deviceId = randomUUID();
  const templateIds = new Set<string>();
  const endpoint = "/api/v1/monitors/pipelines";
  try {
    await addTestCharger(page.request, token, deviceId, deviceId, ["AC1", "AC2", "AC3"]);
    await page.setViewportSize({ width: 1600, height: 1100 });
    await page.goto(`/?create=monitoring&target=${fixtureEntityId(deviceId)}`);
    const setupUrl = page.url();
    const workbench = page.getByRole("region", { name: "Monitoring workbench", exact: true });
    await workbench.getByRole("textbox", { name: "Service name", exact: true }).fill(`Two phases ${deviceId}`);
    await workbench.getByRole("checkbox", { name: "Monitor AC2", exact: true }).uncheck();
    await expect(workbench.getByRole("checkbox", { name: "Monitor AC1", exact: true })).toBeChecked();
    await expect(workbench.getByRole("checkbox", { name: "Monitor AC3", exact: true })).toBeChecked();
    await workbench.getByRole("checkbox", { name: "Monitor AC1", exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath("creation-readings-desktop.png"), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    for (const name of ["AC1", "AC2", "AC3"]) {
      const reading = workbench.getByRole("checkbox", { name: `Monitor ${name}`, exact: true });
      await reading.scrollIntoViewIfNeeded(); await expect(reading).toBeInViewport({ ratio: 1 });
    }
    await expectNoHorizontalScroll(page);
    await page.screenshot({ path: testInfo.outputPath("creation-readings-mobile.png"), fullPage: true });
    await workbench.getByRole("link", { name: "Configure readings in Sources", exact: true }).click();
    await page.getByRole("link", { name: "Return to service setup", exact: true }).click();
    await page.reload();
    await expect(workbench.getByRole("checkbox", { name: "Monitor AC2", exact: true })).not.toBeChecked();
    const template = await savePipelineTemplate(page, `Two phases template ${deviceId}`); templateIds.add(template.id);
    expect(template.draft.input_slots?.map((slot) => slot.label)).toEqual(["AC1", "AC3"]);
    const retainedIds = template.draft.input_slots!.map((slot) => slot.id);
    await page.setViewportSize({ width: 1600, height: 1100 });
    await page.goto(`${new URL(setupUrl).origin}/?pipeline=${template.id}`);
    const editor = page.getByRole("region", { name: "Pipeline editor", exact: true });
    await editor.getByRole("button", { name: "Choose monitoring inputs", exact: true }).click();
    await page.getByRole("searchbox", { name: "Search entities", exact: true }).fill(deviceId);
    await page.getByRole("button", { name: new RegExp(deviceId) }).click();
    await expect(editor.getByRole("combobox", { name: "Reading for AC1", exact: true })).toHaveValue(`${deviceId}:AC1`);
    await expect(editor.getByRole("combobox", { name: "Reading for AC3", exact: true })).toHaveValue(`${deviceId}:AC3`);
    await editor.getByRole("combobox", { name: "Add reading", exact: true }).selectOption(`${deviceId}:AC2`);
    await expect(editor.getByRole("combobox", { name: "Reading for AC2", exact: true })).toHaveValue(`${deviceId}:AC2`);
    await editor.getByRole("button", { name: "Remove reading for AC2", exact: true }).click();
    const saved = await savePipelineTemplate(page);
    expect(saved.id).toBe(template.id);
    expect(saved.draft.input_slots?.map((slot) => slot.id)).toEqual(retainedIds);
    await page.reload();
    await expect(editor.getByRole("combobox", { name: "Reading for AC1", exact: true })).toHaveValue(`${deviceId}:AC1`);
    await expect(editor.getByRole("combobox", { name: "Reading for AC3", exact: true })).toHaveValue(`${deviceId}:AC3`);
    await expect(editor.getByRole("combobox", { name: "Reading for AC2", exact: true })).toHaveCount(0);
  } finally {
    await archivePipelines(page.request, headers, [...templateIds].map(id => `${endpoint}/${id}`));
    await removeTestCharger(page.request, token, deviceId);
  }
});

test("keeps an unnamed graph dirty and undoable across template browsing", async ({ page }) => {
  await openPipelineWorkspace(page);
  await page.setViewportSize({ width: 1600, height: 1100 });
  await page.goto("/?create=monitoring");
  const workbench = page.getByRole("region", { name: "Monitoring workbench", exact: true });
  const name = workbench.getByRole("textbox", { name: "Service name", exact: true });
  const input = workbench.getByLabel("Pipeline graph", { exact: true }).locator('.react-flow__node[data-id="input"]');
  const position = () => input.evaluate((element) => {
    const transform = new DOMMatrix(getComputedStyle(element).transform);
    return { x: transform.e, y: transform.f };
  });
  await expect(input).toBeVisible();
  await expect(name).toHaveValue("");
  const original = await position();
  await input.focus(); await input.press("Enter"); await input.press("ArrowRight");
  await expect.poll(async () => (await position()).x).toBeGreaterThan(original.x);
  const moved = await position();
  await workbench.getByRole("button", { name: "Load template", exact: true }).click();
  await page.getByRole("dialog", { name: "Monitoring templates", exact: true })
    .getByRole("button", { name: "Manage templates", exact: true }).click();
  const library = page.getByRole("region", { name: "Templates", exact: true });
  await expect(library).toBeVisible();
  // The breadcrumb names the setup that the library was opened from.
  await library.getByRole("navigation", { name: "Breadcrumb", exact: true }).getByRole("button", { name: "New service", exact: true }).click();
  await expect(name).toHaveValue(""); await expect.poll(position).toEqual(moved);
  const unloading = page.waitForEvent("dialog");
  const reload = page.evaluate(() => window.location.reload());
  const dialog = await unloading; expect(dialog.type()).toBe("beforeunload"); await dialog.dismiss(); await reload;
  await expect.poll(position).toEqual(moved);
  await workbench.getByRole("button", { name: "Undo graph change", exact: true }).click();
  await expect.poll(position).toEqual(original);
});

for (const acknowledgement of ["after returning", "while in Sources"] as const) {
  test(`keeps one real template save acknowledged ${acknowledgement} and preserves later edits`, async ({ page }) => {
    await openPipelineWorkspace(page);
    await page.setViewportSize({ width: 1600, height: 1100 });
    const token = (await accessToken(page))!;
    const headers = { Authorization: `Bearer ${token}` };
    const deviceId = randomUUID();
    const endpoint = "/api/v1/monitors/pipelines";
    const createdIds = new Set<string>();
    let creates = 0;
    let release!: () => void; let submitted!: () => void;
    const held = new Promise<void>((resolve) => { release = resolve; });
    const saving = new Promise<void>((resolve) => { submitted = resolve; });
    page.on("request", (request) => { if (request.method() === "POST" && new URL(request.url()).pathname === endpoint) creates++; });
    try {
      await addTestCharger(page.request, token, deviceId, deviceId, ["voltage"], { mode: "off", interval_seconds: 10 });
      await page.goto(`/?create=monitoring&target=${fixtureEntityId(deviceId)}`);
      const workbench = page.getByRole("region", { name: "Monitoring workbench", exact: true });
      await workbench.getByRole("textbox", { name: "Service name", exact: true }).fill(`Service ${deviceId}`);
      await openPipelineSettings(workbench, "Component");
      await workbench.getByRole("combobox", { name: "Selected component", exact: true }).selectOption("input");
      const title = workbench.getByRole("textbox", { name: "Node title", exact: true });
      await title.fill("Submitted title");
      await page.route(`**${endpoint}`, async (route) => {
        if (route.request().method() !== "POST") { await route.continue(); return; }
        // Commit to the real database; delay only delivery of its acknowledgement.
        const response = await route.fetch(); expect(response.ok(), await response.text()).toBe(true);
        createdIds.add((await response.json() as PipelineView).id); submitted(); await held; await route.fulfill({ response });
      });
      await workbench.getByRole("button", { name: "Save template", exact: true }).click();
      const saveDialog = page.getByRole("dialog", { name: "Save monitoring template", exact: true });
      await saveDialog.getByRole("textbox", { name: "Template name", exact: true }).fill(`Template ${deviceId}`);
      const delivered = page.waitForResponse((response) => response.request().method() === "POST" && new URL(response.url()).pathname === endpoint);
      await saveDialog.getByRole("button", { name: "Save template", exact: true }).click(); await saving;
      await saveDialog.getByRole("button", { name: "Close save template", exact: true }).click();
      await title.fill("Edited after submission");
      await workbench.getByRole("link", { name: "Configure readings in Sources", exact: true }).click();
      const sources = page.getByRole("main", { name: "Sources workspace", exact: true }); await expect(sources).toBeVisible();
      if (acknowledgement === "after returning") {
        await sources.getByRole("link", { name: "Return to service setup", exact: true }).click();
        await expect(workbench.getByRole("button", { name: "Save template", exact: true })).toBeDisabled();
        await openPipelineSettings(workbench, "Component");
        await workbench.getByRole("combobox", { name: "Selected component", exact: true }).selectOption("input");
        await expect(title).toHaveValue("Edited after submission"); await title.fill("Edited after returning");
      }
      release(); expect((await delivered).ok()).toBe(true);
      if (acknowledgement === "while in Sources") {
        await expect(sources).toBeVisible();
        await sources.getByRole("link", { name: "Return to service setup", exact: true }).click();
      }
      await page.unroute(`**${endpoint}`);
      await openPipelineSettings(workbench, "Component");
      await workbench.getByRole("combobox", { name: "Selected component", exact: true }).selectOption("input");
      const finalTitle = acknowledgement === "after returning" ? "Edited after returning" : "Edited after submission";
      await expect(title).toHaveValue(finalTitle);
      const id = [...createdIds][0]!;
      const first = await page.request.get(`${endpoint}/${id}`, { headers });
      expect((await first.json() as PipelineView).layout.nodes?.input?.label).toBe("Submitted title");
      await savePipelineTemplate(page);
      expect(creates).toBe(1);
      await page.reload(); await openPipelineSettings(workbench, "Component");
      await workbench.getByRole("combobox", { name: "Selected component", exact: true }).selectOption("input");
      await expect(title).toHaveValue(finalTitle);
      await expect(workbench.getByRole("textbox", { name: "Service name", exact: true })).toHaveValue(`Service ${deviceId}`);
    } finally {
      release(); await page.unrouteAll({ behavior: "wait" });
      await archivePipelines(page.request, headers, [...createdIds].map(id => `${endpoint}/${id}`));
      await removeTestCharger(page.request, token, deviceId);
    }
  });
}

test("loads the saved template, saves an independent copy, and fits desktop and mobile layouts", async ({ page }, testInfo) => {
  await openPipelineWorkspace(page);
  const headers = { Authorization: `Bearer ${(await accessToken(page))!}` };
  const endpoint = "/api/v1/monitors/pipelines";
  const ids: string[] = [];
  const unique = randomUUID();
  try {
    const catalog = await (await page.request.get(`${endpoint}/catalog`, { headers })).json() as PipelineCatalog;
    const definition = structuredClone(catalog.templates.find((item) => item.definition.strategy === "adaptive_stream")!.definition);
    definition.input_slots = [{ id: "voltage", label: "Voltage", unit: "V" }];
    const response = await page.request.post(endpoint, { headers, data: { name: `Reusable ${unique}`, definition } });
    const source = await response.json() as PipelineView; ids.push(source.id);
    const published = await page.request.post(`${endpoint}/${source.id}/revisions`, { headers, data: { expected_version: source.version } }); expect(published.ok()).toBe(true);
    const saved = await page.request.put(`${endpoint}/${source.id}/draft`, { headers, data: { expected_version: source.version + 1, definition: { ...definition, input_slots: [{ id: "temperature", label: "Temperature", unit: "°C" }] } } });
    const latest = await saved.json() as PipelineView;
    await page.setViewportSize({ width: 1600, height: 1100 }); await page.goto("/?create=monitoring");
    const workbench = page.getByRole("region", { name: "Monitoring workbench", exact: true });
    await workbench.getByRole("textbox", { name: "Service name", exact: true }).fill("Machine health");
    await expect(workbench.getByRole("button", { name: /Publish revision|Save draft|Start revision/ })).toHaveCount(0);
    await workbench.getByRole("button", { name: "Load template", exact: true }).click();
    const templates = page.getByRole("dialog", { name: "Monitoring templates", exact: true });
    await templates.getByRole("searchbox", { name: "Search templates", exact: true }).fill(source.name);
    await templates.getByRole("button", { name: `Use ${source.name}`, exact: true }).click();
    await expect(templates).toBeHidden();
    await expect(workbench.getByRole("textbox", { name: "Service name", exact: true })).toHaveValue("Machine health");
    await openPipelineSettings(workbench, "Service");
    for (const name of ["Detector learning updates before calibration", "Calibration observations", "Default random seed"])
      await expect(workbench.getByRole("spinbutton", { name, exact: true })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath("creation-learning-desktop.png"), fullPage: true });
    await workbench.getByText("Input slots", { exact: true }).click();
    await expect(workbench.getByRole("textbox", { name: "Unit for temperature", exact: true })).toHaveValue("°C");
    await expect(workbench.getByRole("textbox", { name: "Unit for voltage", exact: true })).toHaveCount(0);
    await workbench.getByRole("button", { name: "Close settings", exact: true }).click();
    for (const theme of ["Light", "Dark"] as const) {
      await setAppearance(page, theme);
      await page.screenshot({ path: testInfo.outputPath(`setup-${theme.toLowerCase()}.png`), fullPage: true });
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: testInfo.outputPath("setup-mobile.png"), fullPage: true });
    await openPipelineSettings(workbench, "Service");
    for (const name of ["Detector learning updates before calibration", "Calibration observations", "Default random seed"]) {
      const field = workbench.getByRole("spinbutton", { name, exact: true });
      await expect(field).toBeVisible();
      await field.scrollIntoViewIfNeeded();
      await expect(field).toBeInViewport({ ratio: 1 });
    }
    await workbench.getByRole("spinbutton", { name: "Detector learning updates before calibration", exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath("creation-learning-mobile.png"), fullPage: true });
    await workbench.getByRole("button", { name: "Close settings", exact: true }).click();
    await workbench.getByRole("button", { name: "Load template", exact: true }).click();
    await expect(templates.getByRole("button", { name: `Use ${source.name}`, exact: true })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath("templates-mobile.png"), fullPage: true });
    await templates.press("Escape");
    await expect(workbench.getByRole("button", { name: "Load template", exact: true })).toBeFocused();
    await workbench.getByRole("button", { name: "Save template", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Save monitoring template", exact: true });
    await page.screenshot({ path: testInfo.outputPath("save-template-mobile.png"), fullPage: true });
    await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
    await expectNoHorizontalScroll(page);
    const copy = await savePipelineTemplate(page, `Independent ${unique}`); ids.push(copy.id);
    expect(copy.draft).toEqual(latest.draft); expect(copy.id).not.toBe(source.id);
    expect(await (await page.request.get(`${endpoint}/${source.id}`, { headers })).json()).toEqual(latest);
    await expect(page.getByRole("region", { name: "Monitoring setup progress", exact: true })).toHaveCount(0);
  } finally {
    await archivePipelines(page.request, headers, ids.map(id => `${endpoint}/${id}`));
  }
});
