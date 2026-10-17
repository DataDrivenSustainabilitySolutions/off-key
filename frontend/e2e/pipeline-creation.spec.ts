import { randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";
import type { PipelineCatalog, PipelineRevisionView, PipelineView } from "../src/types/pipelines.generated";
import { loginPipelineWorkspace } from "./helpers/pipelines";

test("opens the workbench directly and safely edits copies of published and draft templates", async ({ page }, testInfo) => {
  test.setTimeout(180_000);
  await loginPipelineWorkspace(page);
  const token = await page.evaluate(() => localStorage.getItem("auth_token"));
  expect(token).toBeTruthy();
  const headers = { Authorization: `Bearer ${token}` };
  const ids = new Set<string>();
  const unique = randomUUID();
  let release!: () => void;
  let releaseWorkspace!: () => void;
  const held = new Promise<void>((resolve) => { release = resolve; });
  const workspaceHeld = new Promise<void>((resolve) => { releaseWorkspace = resolve; });
  const createPath = "/api/v1/monitors/pipelines";
  const routePattern = `**${createPath}`;
  const theme = async (name: "Light" | "Dark") => {
    await page.getByRole("button", { name: "Application menu", exact: true }).click();
    await page.getByRole("menuitem", { name: "Settings", exact: true }).click();
    await page.getByRole("radio", { name, exact: true }).check();
    await page.getByRole("button", { name: "Close settings", exact: true }).click();
  };
  try {
    const catalogResponse = await page.request.get(`${createPath}/catalog`, { headers });
    expect(catalogResponse.ok(), await catalogResponse.text()).toBe(true);
    const catalog = await catalogResponse.json() as PipelineCatalog;
    const definition = structuredClone(catalog.templates.find((item) => item.definition.strategy === "adaptive_stream")!.definition);
    definition.input_slots = [{ id: "voltage", label: "Voltage", unit: "V" }, { id: "heat", label: "Temperature", unit: "°C" }];
    const createDesign = async (name: string) => {
      const response = await page.request.post(createPath, { headers, data: { name, definition } });
      expect(response.ok(), await response.text()).toBe(true);
      const design = await response.json() as PipelineView;
      ids.add(design.id);
      return design;
    };
    const source = await createDesign(`Published template ${unique}`);
    const unpublished = await createDesign(`Draft template ${unique}`);
    const publishedResponse = await page.request.post(`${createPath}/${source.id}/revisions`, {
      headers, data: { expected_version: source.version },
    });
    expect(publishedResponse.ok(), await publishedResponse.text()).toBe(true);
    const revision = await publishedResponse.json() as PipelineRevisionView;
    const savedResponse = await page.request.put(`${createPath}/${source.id}/draft`, {
      headers, data: { expected_version: source.version + 1,
        definition: { ...definition, input_slots: [{ id: "unpublished_only", label: "Unpublished changes", unit: "A" }] } },
    });
    expect(savedResponse.ok(), await savedResponse.text()).toBe(true);
    const sourceDraft = await savedResponse.json() as PipelineView;

    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Monitoring", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Pipelines", exact: true })).toHaveCount(0);
    let createRequests = 0;
    page.on("request", (request) => {
      if (request.method() === "POST" && new URL(request.url()).pathname === createPath) createRequests++;
    });
    // A direct URL reload waits for real server capabilities, rather than
    // briefly offering legacy creation while the workspace response is delayed.
    await page.route("**/api/v1/monitors/workspace*", async (route) => {
      const response = await route.fetch();
      expect(response.ok(), await response.text()).toBe(true);
      await workspaceHeld;
      await route.fulfill({ response });
    });
    await page.goto("/?create=monitoring");
    await expect(page.getByText("Opening monitoring setup…", { exact: true })).toBeVisible();
    await expect(page.getByRole("region", { name: "Create monitoring service", exact: true })).toHaveCount(0);
    releaseWorkspace();
    const workbench = page.getByRole("region", { name: "Monitoring workbench", exact: true });
    await expect(workbench.getByLabel("Pipeline graph", { exact: true })).toBeVisible();
    await page.unroute("**/api/v1/monitors/workspace*");
    const name = workbench.getByRole("textbox", { name: "Service name", exact: true });
    await expect(name).toHaveAttribute("placeholder", "e.g. Machine health");
    await expect(workbench.getByRole("button", { name: "Choose monitoring inputs", exact: true })).toHaveText("Select an entity");
    const copyName = `Machine health ${unique.slice(0, 8)}`;
    await name.fill(copyName);
    await page.setViewportSize({ width: 1600, height: 1100 });
    await theme("Light");
    await page.screenshot({ path: testInfo.outputPath("creation-workbench.png") });
    await workbench.getByRole("button", { name: "Templates", exact: true }).click();
    const templates = page.getByRole("dialog", { name: "Monitoring templates", exact: true });
    await templates.getByRole("button", { name: "Manage saved designs", exact: true }).click();
    const library = page.getByRole("region", { name: "Saved designs", exact: true });
    await expect(library).toBeVisible();
    await library.getByRole("button", { name: "Back", exact: true }).click();
    await expect(name).toHaveValue(copyName);
    expect(createRequests).toBe(0);

    const load = async (design: PipelineView) => {
      await workbench.getByRole("button", { name: "Templates", exact: true }).click();
      await templates.getByRole("searchbox", { name: "Search saved designs", exact: true }).fill(design.name);
      await templates.getByRole("button", { name: `Use ${design.name}`, exact: true }).click();
    };
    await load(unpublished);
    await expect(workbench.getByText(/Loaded Draft template.*Saved draft · version 1/)).toBeVisible();
    await load(source);
    await expect(workbench.getByText(/Loaded Published template.*Revision 1/)).toBeVisible();
    await expect(name).toHaveValue(copyName);
    await workbench.getByText("Input slots and learning settings", { exact: true }).click();
    await expect(workbench.getByRole("textbox", { name: "Label for voltage", exact: true })).toHaveValue("Voltage");
    await expect(workbench.getByRole("textbox", { name: "Unit for heat", exact: true })).toHaveValue("°C");
    await expect(workbench.getByRole("textbox", { name: "Label for unpublished_only", exact: true })).toHaveCount(0);
    const inspector = workbench.getByRole("complementary", { name: "Monitoring inspector", exact: true });
    const widths = await inspector.evaluate((element) => ({ scroll: element.scrollWidth, visible: element.clientWidth }));
    expect(widths.scroll, "Expanded service settings must fit the inspector width").toBeLessThanOrEqual(widths.visible + 1);
    await page.screenshot({ path: testInfo.outputPath("creation-service-settings.png") });
    await workbench.getByText("Input slots and learning settings", { exact: true }).click();
    expect(createRequests).toBe(0);

    await theme("Dark");
    await page.screenshot({ path: testInfo.outputPath("creation-workbench-dark.png") });
    await page.setViewportSize({ width: 390, height: 844 });
    await workbench.getByRole("button", { name: "inspector", exact: true }).click();
    await expect(name).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath("creation-workbench-mobile.png") });
    await workbench.getByRole("button", { name: "Templates", exact: true }).click();
    await expect(templates).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath("creation-templates-mobile.png") });
    await templates.getByRole("button", { name: "Close templates", exact: true }).click();
    await page.setViewportSize({ width: 1600, height: 1100 });
    await workbench.getByRole("button", { name: "Component settings", exact: true }).click();
    await workbench.getByRole("combobox", { name: "Selected component", exact: true }).selectOption("input");
    const title = workbench.getByRole("textbox", { name: "Node title", exact: true });
    await title.fill("Submitted inputs");
    let submitted!: () => void;
    const saving = new Promise<void>((resolve) => { submitted = resolve; });
    await page.route(routePattern, async (route) => {
      if (route.request().method() !== "POST") { await route.continue(); return; }
      // The real database commits first; only the network acknowledgement is held.
      const response = await route.fetch();
      expect(response.ok(), await response.text()).toBe(true);
      const copied = await response.json() as PipelineView;
      ids.add(copied.id);
      submitted();
      await held;
      await route.fulfill({ response });
    });
    await workbench.getByRole("button", { name: "Save draft", exact: true }).click();
    await saving;
    await title.fill("Edits made while saving");
    release();
    const editor = page.getByRole("region", { name: "Pipeline editor", exact: true });
    await expect(editor).toBeVisible();
    await page.unroute(routePattern);
    expect(createRequests).toBe(1);
    const copyId = new URL(page.url()).searchParams.get("pipeline")!;
    expect(copyId).not.toBe(source.id);
    const copyResponse = await page.request.get(`${createPath}/${copyId}`, { headers });
    expect(copyResponse.ok(), await copyResponse.text()).toBe(true);
    const copy = await copyResponse.json() as PipelineView;
    expect(copy.draft).toEqual(revision.definition);
    expect(copy.layout.nodes?.input?.label).toBe("Submitted inputs");
    await editor.getByRole("combobox", { name: "Selected component", exact: true }).selectOption("input");
    await expect(editor.getByRole("textbox", { name: "Node title", exact: true })).toHaveValue("Edits made while saving");
    await expect(editor.getByText("Unsaved draft changes", { exact: false })).toBeVisible();
    await editor.getByRole("button", { name: "Save draft", exact: true }).click();
    await expect(editor.getByText("Draft saved.", { exact: true })).toBeVisible();
    await page.reload();
    await expect(editor.getByRole("heading", { name: copyName, exact: true })).toBeVisible();
    const unchanged = await page.request.get(`${createPath}/${source.id}`, { headers });
    expect(unchanged.ok(), await unchanged.text()).toBe(true);
    expect(await unchanged.json()).toEqual(sourceDraft);
  } finally {
    release();
    releaseWorkspace();
    await page.unroute(routePattern);
    await page.unroute("**/api/v1/monitors/workspace*");
    for (const id of ids) {
      const response = await page.request.get(`${createPath}/${id}`, { headers });
      expect(response.ok(), await response.text()).toBe(true);
      const design = await response.json() as PipelineView;
      const archived = await page.request.patch(`${createPath}/${id}`, { headers,
        data: { expected_version: design.version, name: design.name, description: design.description, archived: true } });
      expect(archived.ok(), await archived.text()).toBe(true);
    }
  }
});
