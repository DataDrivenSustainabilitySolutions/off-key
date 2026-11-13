import { randomUUID } from "node:crypto";
import { expect, test, type Page } from "@playwright/test";
import type {
  PipelineCatalog,
  PipelineDefinition,
  PipelineView,
} from "../src/types/pipelines.generated";
import { archivePipelines, openPipelineWorkspace } from "./helpers/pipelines";
import { dropPipelineComponent } from "./helpers/pipelineGrid";
import { expectClearPipelineRouting } from "./helpers/pipelineRouting";
import {
  choosePipelineDetector,
  fitPipelineOverview,
  locatePipelineSelection,
  savePipelineTemplate,
  openPipelineSettings,
  expectReadablePipeline,
  expectValidPipeline,
} from "./helpers/pipelineNavigation";
import { accessToken } from "./helpers/auth";
import { setAppearance } from "./helpers/appearance";
import { expectNoHorizontalScroll } from "./helpers/layout";

test.beforeEach(async ({ page }) => openPipelineWorkspace(page));

/** Draws wires between connection dots with the mouse, as a person does. */
function wiring(page: Page) {
  const dot = (id: string, direction: "input" | "output") => page.getByLabel("Pipeline graph", { exact: true })
    .locator(`.react-flow__node[data-id="${id}"] [data-handleid="${direction}"]`);
  const beginWire = async (id: string, direction: "input" | "output") => {
    const box = (await dot(id, direction).boundingBox())!;
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 + 10, box.y + box.height / 2 + 10, { steps: 3 });
  };
  const endWire = async (id: string, direction: "input" | "output") => {
    const box = (await dot(id, direction).boundingBox())!;
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 8 });
    await page.mouse.up();
  };
  return { dot, beginWire, endWire };
}

test("drags from the compact component menu without covering the drop area", async ({ page }) => {
  test.setTimeout(30_000);
  await page.setViewportSize({ width: 1366, height: 900 });
  await page.goto("/?create=monitoring");
  await dropPipelineComponent(page, "Pass through", "features_passthrough_1");
  await expect(page.getByRole("textbox", { name: "Step title", exact: true })).toHaveAttribute("placeholder", "Pass through");
  await expect(page.getByRole("combobox", { name: "Selected step", exact: true })).toHaveValue("features_passthrough_1");
});

for (const strategy of ["static_baseline", "adaptive_stream"] as const) {
  test(`uses a consistent typed visual language for ${strategy}`, async ({
    page,
  }, testInfo) => {
    const token = await accessToken(page);
    const headers = { Authorization: `Bearer ${token}` };
    const response = await page.request.get(
      "/api/v1/pipeline-components",
      { headers },
    );
    expect(response.ok()).toBe(true);
    const catalog = (await response.json()) as PipelineCatalog;
    const definition: PipelineDefinition = structuredClone(
      catalog.templates.find((item) => item.id === strategy)!
        .definition,
    );
    const slot = definition.input_slots![0]!.id;
    definition.nodes!.push(
      {
        id: "raw",
        kind: "transform",
        component: "features.passthrough",
        label: "Raw reference",
      },
      {
        id: "renamed",
        kind: "transform",
        component: "features.rename",
        params: { mapping: { [slot]: "reference_raw" } },
      },
      { id: "merge", kind: "merge", component: "features.merge" },
    );
    definition.edges = definition.edges!.filter(
      (edge) => edge.target !== "detector",
    );
    definition.edges.push(
      { source: "input", target: "raw" },
      { source: "input", target: "renamed" },
      { source: "raw", target: "merge", order: 0 },
      { source: "renamed", target: "merge", order: 127 },
      { source: "merge", target: "detector" },
    );
    const created = await page.request.post("/api/v1/pipelines", {
      headers,
      data: {
        name: `Visual language ${randomUUID()}`,
        definition,
        layout: {
          nodes: {
            input: { x: 0, y: 130 },
            raw: { x: 280, y: 20 },
            renamed: { x: 280, y: 240 },
            merge: { x: 560, y: 130 },
            detector: { x: 840, y: 130 },
            calibrate: { x: 1120, y: 130 },
            policy: { x: 1400, y: 130 },
            output: { x: 1680, y: 130 },
          },
        },
      },
    });
    expect(created.ok(), await created.text()).toBe(true);
    const design = (await created.json()) as PipelineView;
    const endpoint = `/api/v1/pipelines/${design.id}`;
    try {
      await page.setViewportSize({ width: 1366, height: 900 });
      await page.goto(
        `/?view=pipelines&pipeline=${encodeURIComponent(design.id)}`,
      );
      const editor = page.getByRole("region", {
        name: "Pipeline editor",
        exact: true,
      });
      const graph = page.getByLabel("Pipeline graph", { exact: true });
      const selector = editor.getByRole("combobox", {
        name: "Selected step",
        exact: true,
      });
      const node = (id: string) =>
        graph.locator(`.react-flow__node[data-id="${id}"]`);
      await expectReadablePipeline(page);
      await expectClearPipelineRouting(page);
      await expect(editor.getByRole("complementary")).toHaveCount(0);
      await expect(editor.getByRole("searchbox", { name: "Search steps" })).toHaveCount(0);
      await expect(node("input")).toBeInViewport();
      await expect(node("input").locator(".pl-node-operation")).toHaveCount(0);
      const canvasWidth = (await graph.boundingBox())!.width;
      const addComponent = editor.getByRole("button", { name: "Add step", exact: true });
      await addComponent.click();
      const search = page.getByRole("searchbox", { name: "Search steps", exact: true });
      await search.fill("Pass through");
      await expect(page.getByRole("button", { name: "Add Pass through", exact: true })).toBeVisible();
      await search.press("Escape");
      await expect(addComponent).toBeFocused();
      await page.screenshot({ path: testInfo.outputPath(`readable-${strategy}-laptop.png`), fullPage: true });
      await node("input").click();
      await expect(editor.getByRole("button", { name: "Step settings", exact: true })).toHaveAttribute("aria-expanded", "true");
      // Settings dock at the right edge of the full-page canvas instead of narrowing it, and leave the step in view.
      await expect(editor.getByRole("heading", { name: "Step settings", exact: true })).toBeVisible();
      await expect.poll(async () => (await graph.boundingBox())!.width).toBe(canvasWidth);
      await expect.poll(async () => {
        const panel = (await page.locator(".pl-settings-panel").boundingBox())!;
        const canvas = (await graph.boundingBox())!;
        const card = (await node("input").boundingBox())!;
        return Math.abs(panel.x + panel.width - canvas.x - canvas.width) < 1 && Math.abs(panel.y - canvas.y) < 1
          && Math.abs(panel.height - canvas.height) < 1 && card.x + card.width <= panel.x;
      }).toBe(true);
      await editor.getByRole("button", { name: "Close settings", exact: true }).click();
      await expect.poll(async () => (await graph.boundingBox())!.width).toBe(canvasWidth);
      await openPipelineSettings(editor, "Component");
      await expect(
        graph.getByLabel("Graph language", { exact: true }),
      ).toHaveCount(0);
      await expect(node("raw")).toContainText("Raw reference");
      await expect(node("raw")).toContainText("Pass through");
      await expect(graph.locator(".pl-node-ports, .pl-port")).toHaveCount(0);
      await expect(node("raw").getByRole("img", { name: "Input: Features", exact: true })).toHaveAttribute("title", "Input: Features");
      // The compiler's report, when it has arrived, adds the features the dot emits.
      await expect(node("raw").getByRole("img", { name: "Output: Features", exact: true })).toHaveAttribute("title", /^Output: Features(\. .+)?$/);
      // Every detector gives scores; the calibration step turns them into calibrated ones.
      await expect(node("detector").getByRole("img", { name: "Output: Scores", exact: true })).toBeAttached();
      await expect(node("calibrate").getByRole("img", { name: "Output: Calibrated scores", exact: true })).toBeAttached();
      await expect(node("detector")).toContainText(strategy === "static_baseline" ? "Fitted once" : "Learns continuously");
      await expect(node("policy").getByRole("img", { name: "Output: Decisions", exact: true })).toBeAttached();
      const typeColors = await graph.evaluate((element) => {
        const css = getComputedStyle(element);
        return ["features", "scores", "p_values", "decisions"].map((kind) => css.getPropertyValue(`--pl-${kind}`).trim());
      });
      expect(new Set(typeColors).size).toBe(4);
      const mergeLink = graph.getByTestId(
        `rf__edge-${JSON.stringify(["renamed", "merge"])}`,
      );
      await expect(mergeLink).toHaveCount(1);
      await expect(mergeLink).toHaveAttribute("aria-label", /: Features · input 2$/);
      await expect(graph.locator(".react-flow__edge-text")).toHaveCount(0);
      await expect(graph.locator(".react-flow__edge path.react-flow__edge-path")).toHaveCount(definition.edges.length);
      await selector.selectOption("merge");
      await expect(
        editor.getByText(
          "Combine feature columns from the same aligned observation, in the order below.",
          { exact: true },
        ),
      ).toBeVisible();
      // Removing the first branch updates its accessible rank, regardless of storage order.
      await editor
        .getByRole("button", { name: "Disconnect raw from merge", exact: true })
        .click();
      await expect(mergeLink).toHaveAttribute("aria-label", /: Features · input 1$/);
      const upstream = editor.getByRole("combobox", {
        name: "Connect input from",
        exact: true,
      });
      const candidates = await upstream
        .locator("option")
        .evaluateAll((options) =>
          options.map((option) => (option as HTMLOptionElement).value),
        );
      expect(candidates).toContain("raw");
      expect(candidates).not.toContain("detector");
      expect(candidates).not.toContain("policy");
      await editor.getByRole("button", { name: "Close settings", exact: true }).click();
      await fitPipelineOverview(page);
      const { dot, beginWire, endWire } = wiring(page);
      // Mismatching colors cannot connect; an occupied input offers to replace its connection.
      const wireCount = await graph.locator(".react-flow__edge").count();
      await beginWire("detector", "output");
      await expect(dot("merge", "input")).toHaveClass(/is-incompatible/);
      await expect(dot("merge", "input")).toHaveAttribute("title", /Cannot connect Scores to Features/);
      await endWire("merge", "input");
      await expect(graph.locator(".react-flow__edge")).toHaveCount(wireCount);
      const reverse = strategy === "adaptive_stream";
      await beginWire(reverse ? "merge" : "raw", reverse ? "input" : "output");
      await expect(dot(reverse ? "raw" : "merge", reverse ? "output" : "input")).toHaveClass(/is-compatible/);
      if (!reverse) {
        await expect(dot("detector", "input")).toHaveClass(/is-compatible/);
        await expect(dot("detector", "input")).toHaveAttribute("title", /Replaces the connection from Merge features\./);
      }
      await endWire(reverse ? "raw" : "merge", reverse ? "output" : "input");
      await expect(graph.locator(".react-flow__edge")).toHaveCount(wireCount + 1);
      await expect(graph.locator(".is-compatible, .is-incompatible")).toHaveCount(0);
      await openPipelineSettings(editor, "Component");
      await editor.getByRole("button", { name: "Disconnect raw from merge", exact: true }).click();
      // The inspector remains an equivalent keyboard authoring route.
      await upstream.selectOption("raw");
      // The status chip opens the check's result in a popover outside the editor region.
      await expectValidPipeline(page);
      await selector.selectOption("raw");
      await locatePipelineSelection(page);
      for (const handle of ["input", "output"]) {
        const socket = node("raw").locator(`[data-handleid="${handle}"]`);
        const card = (await node("raw").boundingBox())!;
        const bounds = (await socket.boundingBox())!;
        expect(
          Math.abs(bounds.y + bounds.height / 2 - card.y - card.height / 2),
        ).toBeLessThan(3);
        expect(bounds.width).toBeGreaterThanOrEqual(27);
      }
      await page.screenshot({
        path: testInfo.outputPath(`visual-language-${strategy}-light.png`),
        fullPage: true,
      });
      await savePipelineTemplate(page);
      await page.reload();
      await openPipelineSettings(editor, "Component");
      await expect(node("raw")).toContainText("Raw reference");
      await expect(node("raw")).toContainText("Pass through");
      await setAppearance(page, "Dark");
      await fitPipelineOverview(page);
      await graph.getByRole("button", { name: "Readable size", exact: true }).click();
      await expectReadablePipeline(page);
      await page.screenshot({
        path: testInfo.outputPath(`visual-language-${strategy}-dark.png`),
        fullPage: true,
      });
      await expectClearPipelineRouting(page);
      await page.setViewportSize({ width: 390, height: 844 });
      await editor.getByRole("button", { name: "Close settings", exact: true }).click();
      await graph.getByRole("button", { name: "Readable size", exact: true }).click();
      await expectReadablePipeline(page);
      await page.screenshot({ path: testInfo.outputPath(`readable-${strategy}-mobile-canvas.png`), fullPage: true });
      await openPipelineSettings(editor, "Component");
      await selector.selectOption("raw");
      await expect(
        editor.getByRole("textbox", { name: "Step title", exact: true }),
      ).toHaveValue("Raw reference");
      await expectNoHorizontalScroll(page);
      await page.screenshot({
        path: testInfo.outputPath(`visual-language-${strategy}-mobile.png`),
        fullPage: true,
      });
    } finally {
      await archivePipelines(page.request, headers, [endpoint]);
    }
  });
}

test("inserts a step on a wire and replaces an occupied input, both undoable", async ({ page }, testInfo) => {
  const token = await accessToken(page);
  const headers = { Authorization: `Bearer ${token}` };
  const response = await page.request.get("/api/v1/pipeline-components", { headers });
  expect(response.ok()).toBe(true);
  const catalog = (await response.json()) as PipelineCatalog;
  const template = catalog.templates.find((item) => item.id === "adaptive_stream")!;
  const created = await page.request.post("/api/v1/pipelines", {
    headers,
    data: { name: `Wire editing ${randomUUID()}`, definition: template.definition, layout: template.layout },
  });
  expect(created.ok(), await created.text()).toBe(true);
  const design = (await created.json()) as PipelineView;
  const endpoint = `/api/v1/pipelines/${design.id}`;
  try {
    await page.setViewportSize({ width: 1366, height: 900 });
    await page.goto(`/?view=pipelines&pipeline=${encodeURIComponent(design.id)}`);
    const editor = page.getByRole("region", { name: "Pipeline editor", exact: true });
    const graph = page.getByLabel("Pipeline graph", { exact: true });
    const { dot, beginWire, endWire } = wiring(page);
    const wire = (source: string, target: string) => graph.getByTestId(`rf__edge-${JSON.stringify([source, target])}`);
    const scaler = "adaptive_standard_scaler_1";
    await expectReadablePipeline(page);
    await fitPipelineOverview(page);
    // A features output counts the columns that leave it; wires carry no labels.
    await expect(dot("input", "output")).toHaveAttribute("data-count", "1");
    await expect(dot("input", "output")).toHaveAttribute("title", "Output: Features. 1 feature: Value.");
    await expect(graph.locator(".react-flow__edge-text")).toHaveCount(0);
    // The "+" waits on the wire until the wire is pointed at, then takes the pointer.
    const insert = page.getByRole("button", { name: /^Insert a step between Aligned inputs and / });
    await expect(insert).toHaveCSS("opacity", "0");
    await expect(async () => {
      const point = await wire("input", "detector").locator("path.react-flow__edge-path")
        .evaluate((path: SVGPathElement) => {
          const spot = path.getPointAtLength(path.getTotalLength() / 2);
          const matrix = path.getScreenCTM()!;
          return { x: spot.x * matrix.a + matrix.e, y: spot.y * matrix.d + matrix.f };
        });
      await page.mouse.move(point.x, point.y);
      await expect(insert).toHaveCSS("opacity", "1", { timeout: 1_000 });
    }).toPass({ timeout: 10_000 });
    await insert.click();
    const menu = page.getByRole("dialog", { name: "Insert a step", exact: true });
    const search = menu.getByRole("searchbox", { name: "Search steps", exact: true });
    await expect(search).toBeFocused();
    // Only steps that take and give features fit here; the detector and policy are not offered.
    await expect(menu.getByRole("button", { name: "Insert Merge features", exact: true })).toBeVisible();
    await expect(menu.getByRole("button", { name: /^Insert .*(forest|threshold)/i })).toHaveCount(0);
    await search.press("Escape");
    await expect(menu).toBeHidden();
    await expect(insert).toBeFocused();
    // The keyboard reaches the same menu.
    await page.keyboard.press("Enter");
    await expect(search).toBeFocused();
    await search.fill("standard");
    await page.screenshot({ path: testInfo.outputPath("wire-editing-menu.png"), fullPage: true });
    await menu.getByRole("button", { name: "Insert Online standard scaling", exact: true }).click();
    await expect(menu).toBeHidden();
    await expect(editor.getByRole("combobox", { name: "Selected step", exact: true })).toHaveValue(scaler);
    await expect(wire("input", scaler)).toHaveCount(1);
    await expect(wire(scaler, "detector")).toHaveCount(1);
    await expect(wire("input", "detector")).toHaveCount(0);
    await expectClearPipelineRouting(page);
    // The new step reports its own columns once the change is checked.
    await expect(dot(scaler, "output")).toHaveAttribute("data-count", "1");
    await editor.getByRole("button", { name: "Close settings", exact: true }).click();
    await fitPipelineOverview(page);
    // Dropping on a taken input replaces its connection and says which one it was.
    await beginWire("input", "output");
    await expect(dot("detector", "input")).toHaveClass(/is-compatible/);
    await expect(dot("detector", "input")).toHaveAttribute("title",
      "Input: Features. Replaces the connection from Online standard scaling.");
    await page.screenshot({ path: testInfo.outputPath("wire-editing-replace.png"), fullPage: true });
    await endWire("detector", "input");
    await expect(graph.getByText("Replaced the input from Online standard scaling.", { exact: true })).toBeVisible();
    await expect(wire("input", "detector")).toHaveCount(1);
    await expect(wire(scaler, "detector")).toHaveCount(0);
    await expect(wire("input", scaler)).toHaveCount(1);
    const undo = editor.getByRole("button", { name: "Undo graph change", exact: true });
    await undo.click();
    await expect(wire(scaler, "detector")).toHaveCount(1);
    await expect(wire("input", "detector")).toHaveCount(0);
    await undo.click();
    await expect(graph.locator(`.react-flow__node[data-id="${scaler}"]`)).toHaveCount(0);
    await expect(wire("input", "detector")).toHaveCount(1);
    await expectClearPipelineRouting(page);
  } finally {
    await archivePipelines(page.request, headers, [endpoint]);
  }
});

test("lists the features the detector receives and adds a step for one of them", async ({ page }, testInfo) => {
  const token = await accessToken(page);
  const headers = { Authorization: `Bearer ${token}` };
  const response = await page.request.get("/api/v1/pipeline-components", { headers });
  expect(response.ok()).toBe(true);
  const catalog = (await response.json()) as PipelineCatalog;
  const template = catalog.templates.find((item) => item.id === "adaptive_stream")!;
  const created = await page.request.post("/api/v1/pipelines", {
    headers,
    data: { name: `Feature rows ${randomUUID()}`, definition: template.definition, layout: template.layout },
  });
  expect(created.ok(), await created.text()).toBe(true);
  const design = (await created.json()) as PipelineView;
  const endpoint = `/api/v1/pipelines/${design.id}`;
  try {
    await page.setViewportSize({ width: 1366, height: 900 });
    await page.goto(`/?view=pipelines&pipeline=${encodeURIComponent(design.id)}`);
    const editor = page.getByRole("region", { name: "Pipeline editor", exact: true });
    const view = (label: "Graph" | "Features") => page.getByRole("group", { name: "View", exact: true })
      .getByRole("button", { name: label, exact: true });
    await expectReadablePipeline(page);
    await view("Features").click();
    await expect(view("Features")).toHaveAttribute("aria-pressed", "true");
    const features = page.getByRole("region", { name: "Features", exact: true });
    const rows = features.getByRole("list", { name: "Features from readings", exact: true }).getByRole("listitem");
    await expect(rows).toHaveCount(1);
    const row = rows.first();
    const chips = row.locator(".pl-feature-step");
    await expect(row.getByText("Raw", { exact: true })).toBeVisible();
    // A Prepare step from the row goes in before anything learns and uses only this feature.
    await row.getByRole("button", { name: /^Add a step for / }).click();
    const menu = page.getByRole("dialog", { name: /^Add a step for / });
    await menu.getByRole("button", { name: "Add Despike", exact: true }).click();
    await expect(menu).toBeHidden();
    await expect(chips).toHaveText(["Despike"]);
    await expect(editor.getByText("Ready after 11 observations", { exact: true })).toBeVisible();
    await editor.getByRole("button", { name: "Close settings", exact: true }).click();
    // A learned step from the row goes in just before the detector.
    await row.getByRole("button", { name: /^Add a step for / }).click();
    await menu.getByRole("button", { name: "Add Online standard scaling", exact: true }).click();
    await expect(chips).toHaveText(["Despike", "Online standard scaling"]);
    await expectValidPipeline(page);
    await page.screenshot({ path: testInfo.outputPath("features-view.png"), fullPage: true });
    // A chip opens its step, and the graph shows the same order.
    await chips.first().click();
    await expect(editor.getByRole("combobox", { name: "Selected step", exact: true })).toHaveValue("prepare_despike_1");
    await editor.getByRole("button", { name: "Close settings", exact: true }).click();
    await view("Graph").click();
    const graph = page.getByLabel("Pipeline graph", { exact: true });
    const wire = (source: string, target: string) => graph.getByTestId(`rf__edge-${JSON.stringify([source, target])}`);
    await expect(wire("input", "prepare_despike_1")).toHaveCount(1);
    await expect(wire("prepare_despike_1", "adaptive_standard_scaler_1")).toHaveCount(1);
    await expect(wire("adaptive_standard_scaler_1", "detector")).toHaveCount(1);
  } finally {
    await archivePipelines(page.request, headers, [endpoint]);
  }
});

test("combines a second detector at the calibration step and lists each detector's features", async ({ page }, testInfo) => {
  const token = await accessToken(page);
  const headers = { Authorization: `Bearer ${token}` };
  const response = await page.request.get("/api/v1/pipeline-components", { headers });
  expect(response.ok()).toBe(true);
  const catalog = (await response.json()) as PipelineCatalog;
  const template = catalog.templates.find((item) => item.id === "adaptive_stream")!;
  const created = await page.request.post("/api/v1/pipelines", {
    headers,
    data: { name: `Combined detectors ${randomUUID()}`, definition: template.definition, layout: template.layout },
  });
  expect(created.ok(), await created.text()).toBe(true);
  const design = (await created.json()) as PipelineView;
  const endpoint = `/api/v1/pipelines/${design.id}`;
  try {
    await page.setViewportSize({ width: 1366, height: 900 });
    await page.goto(`/?view=pipelines&pipeline=${encodeURIComponent(design.id)}`);
    const editor = page.getByRole("region", { name: "Pipeline editor", exact: true });
    const graph = page.getByLabel("Pipeline graph", { exact: true });
    const node = (id: string) => graph.locator(`.react-flow__node[data-id="${id}"]`);
    const wire = (source: string, target: string) => graph.getByTestId(`rf__edge-${JSON.stringify([source, target])}`);
    const selector = editor.getByRole("combobox", { name: "Selected step", exact: true });
    const reads = template.definition.edges!.find((edge) => edge.target === "detector")!.source;
    await expectReadablePipeline(page);
    await node("detector").click();
    // Another detector reads what the first one reads, and the calibration step takes both.
    await editor.getByRole("button", { name: "Add another detector", exact: true }).click();
    await expect(selector).toHaveValue("detector_2");
    await expect(wire(reads, "detector_2")).toHaveCount(1);
    await expect(wire("detector_2", "calibrate")).toHaveCount(1);
    await expect(wire("detector", "calibrate")).toHaveCount(1);
    await expect(wire("calibrate", "policy")).toHaveCount(1);
    const model = editor.getByRole("combobox", { name: "Detector model", exact: true });
    const current = await model.inputValue();
    const other = (await model.locator("option").evaluateAll((options) =>
      options.map((option) => (option as HTMLOptionElement).value))).find((value) => value !== current)!;
    await model.selectOption(other);
    // The calibration step shows how it combines them once there are two.
    await selector.selectOption("calibrate");
    const combine = editor.getByRole("group", { name: "Combine detectors", exact: true });
    await expect(combine.getByRole("button", { name: "Strongest", exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(node("calibrate")).toContainText("Strongest of 2 detectors");
    await combine.getByRole("button", { name: "Average", exact: true }).click();
    await expect(node("calibrate")).toContainText("Average of 2 detectors");
    await expectValidPipeline(page);
    // A method that adapts takes the exceedance rule along, and the design still checks.
    await expect(editor.getByText("Exact while data stays alike.", { exact: true })).toBeVisible();
    await editor.getByRole("combobox", { name: "Calibration method", exact: true }).selectOption("calibrate.aci");
    await expect(editor.getByText("Long-run alarm rate.", { exact: true })).toBeVisible();
    await expect(node("policy")).toContainText("Exceedance rule");
    await expect(node("calibrate")).toContainText("Average of 2 detectors");
    await expectValidPipeline(page);
    await editor.getByRole("button", { name: "Undo graph change", exact: true }).click();
    await expect(node("policy")).not.toContainText("Exceedance rule");
    await expectValidPipeline(page);
    await page.screenshot({ path: testInfo.outputPath("combined-detectors.png"), fullPage: true });
    await editor.getByRole("button", { name: "Close settings", exact: true }).click();
    // The Features view lists one detector's features at a time.
    await page.getByRole("group", { name: "View", exact: true }).getByRole("button", { name: "Features", exact: true }).click();
    const features = page.getByRole("region", { name: "Features", exact: true });
    const detectors = features.getByRole("group", { name: "Detector", exact: true }).getByRole("button");
    await expect(detectors).toHaveCount(2);
    await expect(detectors.first()).toHaveAttribute("aria-pressed", "true");
    const rows = features.getByRole("list", { name: "Features from readings", exact: true }).getByRole("listitem");
    const first = await rows.allTextContents();
    await detectors.last().click();
    await expect(detectors.last()).toHaveAttribute("aria-pressed", "true");
    await expect(rows).toHaveText(first);
    await page.screenshot({ path: testInfo.outputPath("combined-detectors-features.png"), fullPage: true });
  } finally {
    await archivePipelines(page.request, headers, [endpoint]);
  }
});

test.describe("touch connection dots", () => {
  test.use({ hasTouch: true });

  test("connects in two taps on a phone without opening settings", async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/?create=monitoring");
    const graph = page.getByLabel("Pipeline graph", { exact: true });
    await choosePipelineDetector(page);
    await openPipelineSettings(page, "Component");
    await page.getByRole("combobox", { name: "Selected step", exact: true }).selectOption("detector");
    await page.getByRole("button", { name: "Disconnect input from detector", exact: true }).click();
    await page.getByRole("button", { name: "Close settings", exact: true }).click();
    await expect(graph.getByRole("button", { name: "Readable size", exact: true })).toHaveText("100%");
    const tapDot = async (id: string, direction: string) => {
      const dot = graph.locator(`.react-flow__node[data-id="${id}"] [data-handleid="${direction}"]`);
      await expect(dot).toBeInViewport();
      const box = (await dot.boundingBox())!;
      await page.touchscreen.tap(box.x + box.width / 2, box.y + box.height / 2);
    };
    await tapDot("input", "output");
    const input = graph.locator('.react-flow__node[data-id="detector"] [data-handleid="input"]');
    await expect(input).toHaveClass(/is-compatible/);
    await expect(page.getByRole("complementary")).toHaveCount(0);
    await page.screenshot({ path: testInfo.outputPath("phone-matching-dots.png"), fullPage: true });
    await tapDot("detector", "input");
    await expect(graph.getByTestId(`rf__edge-${JSON.stringify(["input", "detector"])}`)).toHaveCount(1);
    await expect(graph.locator(".is-compatible, .is-incompatible")).toHaveCount(0);
    await expect(page.getByRole("complementary")).toHaveCount(0);
    await expectValidPipeline(page);
  });
});
