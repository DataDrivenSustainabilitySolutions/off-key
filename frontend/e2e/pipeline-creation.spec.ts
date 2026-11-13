import { randomUUID } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";
import type { PipelineCatalog, PipelineDesignFile, PipelineView } from "../src/types/pipelines.generated";
import { addTestCharger, fixtureTarget, removeTestCharger } from "./helpers/collection";
import { archivePipelines, openPipelineWorkspace } from "./helpers/pipelines";
import { openPipelineInput, openPipelineSettings, savePipelineTemplate } from "./helpers/pipelineNavigation";
import { accessToken } from "./helpers/auth";
import { setAppearance } from "./helpers/appearance";
import { expectNoHorizontalScroll } from "./helpers/layout";

test("selects only AC1 and AC3 and preserves named template mappings on desktop and mobile", async ({ page }, testInfo) => {
  await openPipelineWorkspace(page);
  const token = (await accessToken(page))!;
  const headers = { Authorization: `Bearer ${token}` };
  const deviceId = randomUUID();
  const templateIds = new Set<string>();
  const endpoint = "/api/v1/pipelines";
  try {
    await addTestCharger(page.request, token, deviceId, deviceId, ["AC1", "AC2", "AC3"]);
    await page.setViewportSize({ width: 1600, height: 1100 });
    await page.goto(`/?create=monitoring&target=${encodeURIComponent(fixtureTarget(deviceId))}`);
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
    await workbench.getByRole("link", { name: "Review recording in Sources", exact: true }).click();
    await page.getByRole("link", { name: "Return to service setup", exact: true }).click();
    await page.reload();
    await expect(workbench.getByRole("checkbox", { name: "Monitor AC2", exact: true })).not.toBeChecked();
    const template = await savePipelineTemplate(page, `Two phases template ${deviceId}`); templateIds.add(template.id);
    expect(template.draft.input_slots?.map((slot) => slot.label)).toEqual(["AC1", "AC3"]);
    const retainedIds = template.draft.input_slots!.map((slot) => slot.id);
    await page.setViewportSize({ width: 1600, height: 1100 });
    await page.goto(`${new URL(setupUrl).origin}/?pipeline=${template.id}`);
    const editor = page.getByRole("region", { name: "Pipeline editor", exact: true });
    await openPipelineInput(editor);
    await editor.getByRole("button", { name: "Choose monitoring inputs", exact: true }).click();
    const choices = page.getByRole("dialog", { name: "Choose monitoring inputs", exact: true });
    await choices.getByRole("searchbox", { name: "Search entities", exact: true }).fill(deviceId);
    await choices.getByRole("button", { name: new RegExp(deviceId) }).click();
    await expect(editor.getByRole("combobox", { name: "Reading for AC1", exact: true })).toHaveValue(`${deviceId}:AC1`);
    await expect(editor.getByRole("combobox", { name: "Reading for AC3", exact: true })).toHaveValue(`${deviceId}:AC3`);
    await editor.getByRole("combobox", { name: "Add reading", exact: true }).selectOption(`${deviceId}:AC2`);
    await expect(editor.getByRole("combobox", { name: "Reading for AC2", exact: true })).toHaveValue(`${deviceId}:AC2`);
    await editor.getByRole("button", { name: "Remove reading for AC2", exact: true }).click();
    const saved = await savePipelineTemplate(page);
    expect(saved.id).toBe(template.id);
    expect(saved.draft.input_slots?.map((slot) => slot.id)).toEqual(retainedIds);
    await page.reload();
    await openPipelineInput(editor);
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
  // The design can be tried on recorded values before it monitors anything. Its panel docks where the
  // settings do, and without a detector there is nothing to run yet.
  await workbench.getByRole("button", { name: "Test on history", exact: true }).click();
  await expect(workbench.getByRole("heading", { name: "Test on history", exact: true })).toBeVisible();
  await expect(workbench.getByRole("combobox", { name: "Values", exact: true })).toHaveValue("window:week");
  await expect(workbench.getByRole("button", { name: "Run test", exact: true })).toBeDisabled();
  await expect(workbench.getByText("The design is not ready to run.", { exact: false })).toBeVisible();
  await workbench.getByRole("button", { name: "Close test", exact: true }).click();
  await expect(workbench.getByRole("heading", { name: "Test on history", exact: true })).toBeHidden();
  // A step's settings keep the values it had in the last test folded away, and lead to the test until there is one.
  await workbench.getByRole("button", { name: "Step settings", exact: true }).click();
  await workbench.getByText("Values in the last test", { exact: true }).click();
  await workbench.getByRole("button", { name: "Open the test", exact: true }).click();
  await expect(workbench.getByRole("heading", { name: "Test on history", exact: true })).toBeVisible();
});

test("chooses several steps and copies, moves and removes them together", async ({ page, context }) => {
  await openPipelineWorkspace(page);
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.setViewportSize({ width: 1600, height: 1100 });
  await page.goto("/?create=monitoring");
  const workbench = page.getByRole("region", { name: "Monitoring workbench", exact: true });
  const graph = workbench.getByLabel("Pipeline graph", { exact: true });
  const cards = graph.locator(".react-flow__node");
  const chosen = graph.locator(".react-flow__node.selected");
  const card = (name: string) => graph.locator(`.react-flow__node[aria-label="${name}"]`);
  const said = graph.getByRole("status");
  const settings = workbench.getByRole("heading", { name: "Step settings", exact: true });
  const closeSettings = () => workbench.getByRole("button", { name: "Close settings", exact: true }).click();
  /** New steps are brought into view; wait until the view has come to rest around one. */
  const atRest = async (name: string) => {
    // A scaled view places a card on fractions of a pixel, so it is never counted as wholly inside.
    await expect(card(name)).toBeInViewport({ ratio: 0.99 });
    let last = "";
    await expect.poll(async () => {
      const now = JSON.stringify(await card(name).boundingBox());
      const same = now === last;
      last = now;
      return same;
    }).toBe(true);
  };
  for (const name of ["Smooth", "Despike"]) {
    await workbench.getByRole("button", { name: "Add step", exact: true }).click();
    await page.getByRole("button", { name: `Add ${name}`, exact: true }).click();
  }
  await closeSettings();
  const count = await cards.count();

  // A click chooses one step and shows its settings; with Shift another joins it and no settings open.
  await card("Smooth").click();
  await expect(settings).toBeVisible();
  await closeSettings();
  await card("Despike").click({ modifiers: ["Shift"] });
  await expect(chosen).toHaveCount(2);
  await expect(settings).toBeHidden();
  await workbench.getByRole("button", { name: "Step settings", exact: true }).click();
  await expect(workbench.getByRole("combobox", { name: "Selected step", exact: true })).toHaveValue("");
  await expect(workbench.getByRole("list", { name: "Chosen steps", exact: true }).getByRole("button")).toHaveText(["Smooth", "Despike"]);
  await closeSettings();

  // Copies travel through the clipboard and arrive chosen, so they can be moved at once.
  await page.keyboard.press("ControlOrMeta+c");
  await expect(said).toHaveText("Copied 2 steps.");
  await graph.hover();
  await page.keyboard.press("ControlOrMeta+v");
  await expect(said).toHaveText("Pasted 2 steps.");
  await expect(cards).toHaveCount(count + 2);
  await expect(chosen).toHaveCount(2);
  await expect(card("Smooth 2")).toHaveClass(/selected/);
  await atRest("Despike 2");
  await page.keyboard.press("ControlOrMeta+d");
  await expect(said).toHaveText("Duplicated 2 steps.");
  await expect(cards).toHaveCount(count + 4);
  await expect(card("Despike 2 copy")).toHaveClass(/selected/);
  await expect(settings).toBeHidden();
  await atRest("Despike 2 copy");

  // Dragging one of them takes the other along.
  const place = (name: string) => card(name).evaluate((element) => element.getBoundingClientRect().left);
  const before = [await place("Smooth 2 copy"), await place("Despike 2 copy")];
  const grip = (await card("Smooth 2 copy").boundingBox())!;
  await page.mouse.move(grip.x + 40, grip.y + 20);
  await page.mouse.down();
  await page.mouse.move(grip.x + 136, grip.y + 20, { steps: 6 });
  await page.mouse.up();
  await expect.poll(async () => [await place("Smooth 2 copy") - before[0]!, await place("Despike 2 copy") - before[1]!]
    .every((moved) => moved > 48)).toBe(true);
  await expect(chosen).toHaveCount(2);

  // Their menu answers for both; one undo brings both back.
  await card("Despike 2 copy").click({ button: "right" });
  const menu = page.getByRole("menu", { name: "2 steps", exact: true });
  await expect(menu.getByRole("menuitem")).toHaveText([/^Duplicate/, /^Copy/, /^Cut/, /^Switch off/, /^Delete/]);
  await menu.getByRole("menuitem", { name: "Delete", exact: true }).click();
  await expect(cards).toHaveCount(count + 2);
  await page.keyboard.press("ControlOrMeta+z");
  await expect(cards).toHaveCount(count + 4);

  // Shift draws a box that takes every step it touches; Escape lets them go.
  await workbench.getByRole("button", { name: "Fit entire graph", exact: true }).click();
  await atRest("Despike 2 copy");
  const all = await cards.evaluateAll((elements) => {
    const boxes = elements.map((element) => element.getBoundingClientRect());
    return { left: Math.min(...boxes.map((box) => box.left)), top: Math.min(...boxes.map((box) => box.top)),
      right: Math.max(...boxes.map((box) => box.right)), bottom: Math.max(...boxes.map((box) => box.bottom)) };
  });
  await page.keyboard.down("Shift");
  await page.mouse.move(all.left - 16, all.top - 16);
  await page.mouse.down();
  await page.mouse.move(all.right - 40, all.bottom - 40, { steps: 8 });
  await page.mouse.up();
  await page.keyboard.up("Shift");
  await expect(chosen).toHaveCount(count + 4);
  await expect(settings).toBeHidden();
  await page.keyboard.press("Escape");
  await expect(chosen).toHaveCount(0);

  // Zooming out stops where cards can still be told apart; once the canvas is in focus, 1 shows the whole graph.
  const zoom = () => graph.locator(".react-flow__viewport").evaluate((element) => new DOMMatrix(getComputedStyle(element).transform).a);
  await graph.hover();
  for (let turn = 0; turn < 30; turn += 1) await page.mouse.wheel(0, 600);
  await expect.poll(zoom).toBe(0.25);
  const corner = (await graph.boundingBox())!;
  await page.mouse.click(corner.x + 12, corner.y + 12);
  await page.keyboard.press("1");
  await expect.poll(zoom).toBeGreaterThan(0.25);
  await atRest("Despike 2 copy");

  // The keys are listed on the canvas, and A adds a step where the pointer is.
  await page.keyboard.press("?");
  const keys = page.getByRole("dialog", { name: "Keyboard shortcuts", exact: true });
  await expect(keys.getByText("Whole graph", { exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(keys).toBeHidden();
  // The list hands the keys back to the canvas a moment after it closes.
  await expect(workbench.getByRole("button", { name: "Keyboard shortcuts", exact: true })).toBeFocused();
  await page.keyboard.press("a");
  const search = page.getByRole("searchbox", { name: "Search steps", exact: true });
  await search.fill("Despike");
  await search.press("Enter");
  await expect(cards).toHaveCount(count + 5);
  await closeSettings();

  // A text field keeps the keys for its own text.
  const name = workbench.getByRole("textbox", { name: "Service name", exact: true });
  await name.fill("Charger");
  await name.press("ControlOrMeta+a");
  await name.press("ControlOrMeta+c");
  await name.press("ControlOrMeta+v");
  await name.press("ControlOrMeta+v");
  await expect(name).toHaveValue("ChargerCharger");
  await name.press("a");
  await expect(name).toHaveValue("ChargerChargera");
  await expect(cards).toHaveCount(count + 5);
});

test("switches a step off without removing it, and on again as it was", async ({ page }) => {
  await openPipelineWorkspace(page);
  await page.setViewportSize({ width: 1600, height: 1100 });
  await page.goto("/?create=monitoring");
  const workbench = page.getByRole("region", { name: "Monitoring workbench", exact: true });
  const graph = workbench.getByLabel("Pipeline graph", { exact: true });
  const cards = graph.locator(".react-flow__node");
  const card = (name: string) => graph.locator(`.react-flow__node[aria-label="${name}"]`);
  const said = graph.getByRole("status");
  const closeSettings = () => workbench.getByRole("button", { name: "Close settings", exact: true }).click();
  const window = workbench.getByRole("spinbutton", { name: "Window", exact: true });
  const off = workbench.getByText("This step is switched off. Features pass through it unchanged, and its settings are kept.");
  await workbench.getByRole("button", { name: "Add step", exact: true }).click();
  await page.getByRole("button", { name: "Add Smooth", exact: true }).click();
  await window.fill("7");
  await closeSettings();
  const count = await cards.count();

  // The menu of a step that changes features switches it off: the card stays where it is and says so.
  await card("Smooth").click({ button: "right" });
  await page.getByRole("menu", { name: "Smooth", exact: true }).getByRole("menuitem", { name: /^Switch off/ }).click();
  await expect(said).toHaveText("Switched off 1 step.");
  await expect(card("Smooth").locator(".pl-node")).toHaveClass(/is-off/);
  await expect(card("Smooth")).toContainText("Switched off");
  await expect(cards).toHaveCount(count);

  // Its settings are kept, not shown, and it comes back with them.
  await card("Smooth").click();
  await expect(off).toBeVisible();
  await expect(window).toBeHidden();
  await workbench.getByRole("button", { name: "Switch on", exact: true }).click();
  await expect(off).toBeHidden();
  await expect(window).toHaveValue("7");
  await expect(card("Smooth").locator(".pl-node")).not.toHaveClass(/is-off/);
  await closeSettings();

  // The key does the same for the chosen step, both ways, and one undo takes a switch back.
  await page.keyboard.press("ControlOrMeta+b");
  await expect(said).toHaveText("Switched off 1 step.");
  await expect(card("Smooth").locator(".pl-node")).toHaveClass(/is-off/);
  await page.keyboard.press("ControlOrMeta+b");
  await expect(said).toHaveText("Switched on 1 step.");
  await expect(card("Smooth").locator(".pl-node")).not.toHaveClass(/is-off/);
  await page.keyboard.press("ControlOrMeta+z");
  await expect(card("Smooth").locator(".pl-node")).toHaveClass(/is-off/);
  await page.keyboard.press("ControlOrMeta+z");
  await expect(card("Smooth").locator(".pl-node")).not.toHaveClass(/is-off/);

  // A step that does not change features has no such entry, and the key says why.
  const input = cards.first();
  await input.click({ button: "right" });
  await expect(page.getByRole("menu").getByRole("menuitem", { name: /^Rename/ })).toBeVisible();
  await expect(page.getByRole("menu").getByRole("menuitem", { name: /^Switch o/ })).toHaveCount(0);
  await page.keyboard.press("Escape");
  await input.click();
  await closeSettings();
  await page.keyboard.press("ControlOrMeta+b");
  await expect(said).toHaveText("Only a step that changes features can be switched off.");
});

test("writes notes on the canvas, moves them and removes them", async ({ page }) => {
  await openPipelineWorkspace(page);
  await page.setViewportSize({ width: 1600, height: 1100 });
  await page.goto("/?create=monitoring");
  const workbench = page.getByRole("region", { name: "Monitoring workbench", exact: true });
  const graph = workbench.getByLabel("Pipeline graph", { exact: true });
  const cards = graph.locator(".react-flow__node");
  const notes = graph.getByRole("note");
  const field = graph.getByRole("textbox", { name: "Note", exact: true });
  await expect(cards.first()).toBeVisible();
  await workbench.getByRole("button", { name: "Close settings", exact: true }).click();
  const count = await cards.count();
  const box = (await graph.boundingBox())!;
  const empty = { x: box.x + 420, y: box.y + box.height - 260 };

  // N starts a note where the pointer is. Enter is a new line of it; Ctrl or Cmd with Enter keeps it.
  await page.mouse.click(empty.x, empty.y);
  await page.keyboard.press("n");
  await expect(field).toBeFocused();
  await page.keyboard.type("Smooth first.");
  await page.keyboard.press("Enter");
  await page.keyboard.type("The current sensor is noisy.");
  await page.keyboard.press("ControlOrMeta+Enter");
  await expect(notes).toHaveText(["Smooth first. The current sensor is noisy."]);
  await expect(notes.first()).toBeFocused();
  await expect(cards).toHaveCount(count);

  // The menu of empty canvas adds one as well, and leaving the field keeps what was written.
  await page.mouse.click(empty.x + 400, empty.y, { button: "right" });
  await page.getByRole("menu", { name: "Add a step", exact: true }).getByRole("menuitem", { name: /^Add a note/ }).click();
  await expect(field).toBeFocused();
  await page.keyboard.type("Agreed with the depot.");
  await page.mouse.click(empty.x + 400, empty.y + 140);
  await expect(notes).toHaveText(["Smooth first. The current sensor is noisy.", "Agreed with the depot."]);

  // A note moves with the pointer, and the cards stay where they are.
  const first = notes.first();
  const place = async () => { const at = (await first.boundingBox())!; return [Math.round(at.x), Math.round(at.y)]; };
  const before = await place();
  const stood = await cards.first().boundingBox();
  await page.mouse.move(before[0]! + 30, before[1]! + 12);
  await page.mouse.down();
  await page.mouse.move(before[0]! + 190, before[1]! - 68, { steps: 6 });
  await page.mouse.up();
  await expect.poll(async () => { const now = await place(); return now[0]! - before[0]! > 120 && before[1]! - now[1]! > 48; }).toBe(true);
  expect(await cards.first().boundingBox()).toEqual(stood);

  // A double-click changes it in its place, and Escape leaves it as it was.
  await first.dblclick();
  await expect(field).toHaveValue("Smooth first.\nThe current sensor is noisy.");
  await page.keyboard.type(" And more.");
  await page.keyboard.press("Escape");
  await expect(first).toHaveText("Smooth first. The current sensor is noisy.");

  // Its menu removes it, Undo brings it back, and Delete removes the one in focus.
  await first.click({ button: "right" });
  await page.getByRole("menu", { name: "Note", exact: true }).getByRole("menuitem", { name: /^Delete/ }).click();
  await expect(notes).toHaveText(["Agreed with the depot."]);
  await page.keyboard.press("ControlOrMeta+z");
  await expect(notes).toHaveCount(2);
  await notes.last().focus();
  await page.keyboard.press("Delete");
  await expect(notes).toHaveText(["Smooth first. The current sensor is noisy."]);
  await expect(cards).toHaveCount(count);

  // The list of keys names the keys for notes.
  await page.keyboard.press("?");
  await expect(page.getByRole("dialog", { name: "Keyboard shortcuts", exact: true }).getByText("Add a note", { exact: true })).toBeVisible();
});

test("downloads a design as a file and opens the file again", async ({ page }, testInfo) => {
  await openPipelineWorkspace(page);
  await page.setViewportSize({ width: 1600, height: 1100 });
  await page.goto("/?create=monitoring");
  const workbench = page.getByRole("region", { name: "Monitoring workbench", exact: true });
  const graph = workbench.getByLabel("Pipeline graph", { exact: true });
  const cards = graph.locator(".react-flow__node");
  const name = workbench.getByRole("textbox", { name: "Service name", exact: true });
  await workbench.getByRole("button", { name: "Add step", exact: true }).click();
  await page.getByRole("button", { name: "Add Smooth", exact: true }).click();
  await workbench.getByRole("textbox", { name: "Step title", exact: true }).fill("Calm it down");
  await workbench.getByRole("button", { name: "Close settings", exact: true }).click();
  const titled = graph.locator('.react-flow__node[aria-label="Calm it down"]');
  await expect(titled).toBeVisible();
  const count = await cards.count();

  // The dialog that saves a template also hands the design over as a file, under the name entered there.
  await workbench.getByRole("button", { name: "Save template", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Save monitoring template", exact: true });
  await dialog.getByRole("textbox", { name: "Template name", exact: true }).fill("Charger health");
  const downloading = page.waitForEvent("download");
  await dialog.getByRole("button", { name: "Download as a file", exact: true }).click();
  const download = await downloading;
  expect(download.suggestedFilename()).toBe("charger-health.design.json");
  const saved = testInfo.outputPath(download.suggestedFilename());
  await download.saveAs(saved);
  await expect(dialog).toBeHidden();
  const file = JSON.parse(await readFile(saved, "utf8")) as PipelineDesignFile;
  expect(file).toMatchObject({ format: "aberration-design", schema_version: 1, name: "Charger health" });
  expect(file.definition.nodes).toHaveLength(count);
  // A title is part of the design, so it travels in the definition.
  expect(file.definition.nodes?.map((node) => node.label)).toContain("Calm it down");

  // Start again, and open the file from the list of templates.
  await workbench.getByRole("button", { name: "Reset", exact: true }).click();
  await page.getByRole("button", { name: "Discard and start again", exact: true }).click();
  await expect(cards).toHaveCount(count - 1);
  await expect(name).toHaveValue("");
  const open = async (path: string) => {
    await workbench.getByRole("button", { name: "Load template", exact: true }).click();
    const choosing = page.waitForEvent("filechooser");
    await page.getByRole("dialog", { name: "Monitoring templates", exact: true }).getByRole("button", { name: "Open a file…", exact: true }).click();
    await (await choosing).setFiles(path);
  };
  await open(saved);
  await expect(cards).toHaveCount(count);
  await expect(titled).toBeVisible();
  await expect(name).toHaveValue("Charger health");
  // The design that was there comes back with Undo.
  await workbench.getByRole("button", { name: "Undo graph change", exact: true }).click();
  await expect(cards).toHaveCount(count - 1);

  // A design another tool wrote: its steps have no places, and one carries its title itself.
  const written = testInfo.outputPath("written.design.json");
  await writeFile(written, JSON.stringify({ format: "aberration-design", name: "Written elsewhere", definition: {
    input_slots: [{ id: "value", label: "Value" }],
    nodes: [{ id: "input", kind: "source", component: "source.aligned" },
      { id: "despike", kind: "transform", component: "prepare.despike", label: "Drop the spikes" }],
    edges: [{ source: "input", target: "despike" }],
  } }));
  await open(written);
  await expect(cards).toHaveCount(2);
  await expect(graph.locator('.react-flow__node[aria-label="Drop the spikes"]')).toBeVisible();

  // Any other file is refused with the reason, and the canvas stays as it is.
  const other = testInfo.outputPath("other.json");
  await writeFile(other, JSON.stringify({ format: "aberration-system", schema_version: 1 }));
  await open(other);
  await expect(workbench.getByRole("alert")).toHaveText('This file is not a design. A design file says "format": "aberration-design".');
  const malformed = testInfo.outputPath("malformed.design.json");
  await writeFile(malformed, JSON.stringify({ format: "aberration-design", definition: { nodes: [{ id: "input", kind: "wizard", component: "source.aligned" }] } }));
  await open(malformed);
  await expect(workbench.getByRole("alert")).toContainText("The design in this file cannot be read. definition.nodes.0.kind:");
  await expect(cards).toHaveCount(2);
});

for (const acknowledgement of ["after returning", "while in Sources"] as const) {
  test(`keeps one real template save acknowledged ${acknowledgement} and preserves later edits`, async ({ page }) => {
    await openPipelineWorkspace(page);
    await page.setViewportSize({ width: 1600, height: 1100 });
    const token = (await accessToken(page))!;
    const headers = { Authorization: `Bearer ${token}` };
    const deviceId = randomUUID();
    const endpoint = "/api/v1/pipelines";
    const createdIds = new Set<string>();
    let creates = 0;
    let release!: () => void; let submitted!: () => void;
    const held = new Promise<void>((resolve) => { release = resolve; });
    const saving = new Promise<void>((resolve) => { submitted = resolve; });
    page.on("request", (request) => { if (request.method() === "POST" && new URL(request.url()).pathname === endpoint) creates++; });
    try {
      await addTestCharger(page.request, token, deviceId, deviceId, ["voltage"], { mode: "off", interval_seconds: 10 });
      await page.goto(`/?create=monitoring&target=${encodeURIComponent(fixtureTarget(deviceId))}`);
      const workbench = page.getByRole("region", { name: "Monitoring workbench", exact: true });
      await workbench.getByRole("textbox", { name: "Service name", exact: true }).fill(`Service ${deviceId}`);
      await openPipelineSettings(workbench, "Component");
      await workbench.getByRole("combobox", { name: "Selected step", exact: true }).selectOption("input");
      const title = workbench.getByRole("textbox", { name: "Step title", exact: true });
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
      await saveDialog.getByRole("button", { name: "Save template", exact: true }).click(); await saving;
      await saveDialog.getByRole("button", { name: "Close save template", exact: true }).click();
      await title.fill("Edited after submission");
      await workbench.getByRole("link", { name: "Turn on recording in Sources", exact: true }).click();
      const sources = page.getByRole("main", { name: "Sources workspace", exact: true }); await expect(sources).toBeVisible();
      if (acknowledgement === "after returning") {
        await sources.getByRole("link", { name: "Return to service setup", exact: true }).click();
        await expect(workbench.getByRole("button", { name: "Save template", exact: true })).toBeDisabled();
        await openPipelineSettings(workbench, "Component");
        await workbench.getByRole("combobox", { name: "Selected step", exact: true }).selectOption("input");
        await expect(title).toHaveValue("Edited after submission"); await title.fill("Edited after returning");
      }
      const delivered = page.waitForResponse((response) => response.request().method() === "POST" && new URL(response.url()).pathname === endpoint);
      release(); expect((await delivered).ok()).toBe(true);
      if (acknowledgement === "while in Sources") {
        await expect(sources).toBeVisible();
        await sources.getByRole("link", { name: "Return to service setup", exact: true }).click();
      }
      await page.unroute(`**${endpoint}`);
      await openPipelineSettings(workbench, "Component");
      await workbench.getByRole("combobox", { name: "Selected step", exact: true }).selectOption("input");
      const finalTitle = acknowledgement === "after returning" ? "Edited after returning" : "Edited after submission";
      await expect(title).toHaveValue(finalTitle);
      const id = [...createdIds][0]!;
      const first = await page.request.get(`${endpoint}/${id}`, { headers });
      expect((await first.json() as PipelineView).draft.nodes?.find((node) => node.id === "input")?.label).toBe("Submitted title");
      await savePipelineTemplate(page);
      expect(creates).toBe(1);
      await page.reload(); await openPipelineSettings(workbench, "Component");
      await workbench.getByRole("combobox", { name: "Selected step", exact: true }).selectOption("input");
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
  const endpoint = "/api/v1/pipelines";
  const ids: string[] = [];
  const unique = randomUUID();
  try {
    const catalog = await (await page.request.get("/api/v1/pipeline-components", { headers })).json() as PipelineCatalog;
    const definition = structuredClone(catalog.templates.find((item) => item.id === "adaptive_stream")!.definition);
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
