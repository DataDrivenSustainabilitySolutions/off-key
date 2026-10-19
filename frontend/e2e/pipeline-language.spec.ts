import { randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";
import type {
  PipelineCatalog,
  PipelineDefinition,
  PipelineView,
} from "../src/types/pipelines.generated";
import { loginPipelineWorkspace } from "./helpers/pipelines";
import { dropPipelineComponent } from "./helpers/pipelineGrid";
import { expectClearPipelineRouting } from "./helpers/pipelineRouting";
import {
  fitPipelineOverview,
  locatePipelineSelection,
  openPipelineSettings,
  expectReadablePipeline,
} from "./helpers/pipelineNavigation";
import { accessToken } from "./helpers/auth";

test.beforeEach(async ({ page }) => loginPipelineWorkspace(page));

test("drags from the compact component menu without covering the drop area", async ({ page }) => {
  test.setTimeout(30_000);
  await page.setViewportSize({ width: 1366, height: 900 });
  await page.goto("/?create=monitoring");
  await dropPipelineComponent(page, "Pass through", "features_passthrough_1");
  await expect(page.getByRole("textbox", { name: "Node title", exact: true })).toHaveAttribute("placeholder", "Pass through");
  await expect(page.getByRole("combobox", { name: "Selected component", exact: true })).toHaveValue("features_passthrough_1");
});

for (const strategy of ["static_baseline", "adaptive_stream"] as const) {
  test(`uses a consistent typed visual language for ${strategy}`, async ({
    page,
  }, testInfo) => {
    const token = await accessToken(page);
    const headers = { Authorization: `Bearer ${token}` };
    const response = await page.request.get(
      "/api/v1/monitors/pipelines/catalog",
      { headers },
    );
    expect(response.ok()).toBe(true);
    const catalog = (await response.json()) as PipelineCatalog;
    const definition: PipelineDefinition = structuredClone(
      catalog.templates.find((item) => item.definition.strategy === strategy)!
        .definition,
    );
    const slot = definition.input_slots![0]!.id;
    definition.nodes!.push(
      { id: "raw", kind: "transform", component: "features.passthrough" },
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
    const created = await page.request.post("/api/v1/monitors/pipelines", {
      headers,
      data: {
        name: `Visual language ${randomUUID()}`,
        definition,
        layout: {
          nodes: {
            input: { x: 0, y: 130 },
            raw: { x: 280, y: 20, label: "Raw reference" },
            renamed: { x: 280, y: 240 },
            merge: { x: 560, y: 130 },
            detector: { x: 840, y: 130 },
            policy: { x: 1120, y: 130 },
            output: { x: 1400, y: 130 },
          },
        },
      },
    });
    expect(created.ok(), await created.text()).toBe(true);
    const design = (await created.json()) as PipelineView;
    const endpoint = `/api/v1/monitors/pipelines/${design.id}`;
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
        name: "Selected component",
        exact: true,
      });
      const node = (id: string) =>
        graph.locator(`.react-flow__node[data-id="${id}"]`);
      await expectReadablePipeline(page);
      await expectClearPipelineRouting(page);
      await expect(editor.getByRole("complementary")).toHaveCount(0);
      await expect(editor.getByRole("searchbox", { name: "Search components" })).toHaveCount(0);
      await expect(node("input")).toBeInViewport();
      await expect(node("input").locator(".pl-node-operation")).toHaveCount(0);
      const canvasWidth = (await graph.boundingBox())!.width;
      const addComponent = editor.getByRole("button", { name: "Add component", exact: true });
      await addComponent.click();
      const search = page.getByRole("searchbox", { name: "Search components", exact: true });
      await search.fill("Pass through");
      await expect(page.getByRole("button", { name: "Add Pass through", exact: true })).toBeVisible();
      await search.press("Escape");
      await expect(addComponent).toBeFocused();
      await page.screenshot({ path: testInfo.outputPath(`readable-${strategy}-laptop.png`), fullPage: true });
      await node("input").click();
      await expect(editor.getByRole("button", { name: "Component settings", exact: true })).toHaveAttribute("aria-expanded", "true");
      await expect.poll(async () => (await graph.boundingBox())!.width).toBeLessThan(canvasWidth - 250);
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
      await expect(node("raw").getByRole("img", { name: "Output: Features", exact: true })).toHaveAttribute("title", "Output: Features");
      await expect(node("detector").getByRole("img", {
        name: strategy === "static_baseline" ? "Output: P-values" : "Output: Scores", exact: true,
      })).toBeAttached();
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
      const dot = (id: string, direction: "input" | "output") => node(id).locator(`[data-handleid="${direction}"]`);
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
      // Mismatching colors cannot connect, and occupied inputs stay unavailable.
      const wireCount = await graph.locator(".react-flow__edge").count();
      await beginWire("detector", "output");
      await expect(dot("merge", "input")).toHaveClass(/is-incompatible/);
      await expect(dot("merge", "input")).toHaveAttribute("title", /Cannot connect (P-values|Scores) to Features/);
      await endWire("merge", "input");
      await expect(graph.locator(".react-flow__edge")).toHaveCount(wireCount);
      const reverse = strategy === "adaptive_stream";
      await beginWire(reverse ? "merge" : "raw", reverse ? "input" : "output");
      await expect(dot(reverse ? "raw" : "merge", reverse ? "output" : "input")).toHaveClass(/is-compatible/);
      if (!reverse) {
        await expect(dot("detector", "input")).toHaveClass(/is-incompatible/);
        await expect(dot("detector", "input")).toHaveAttribute("title", /input is occupied/);
      }
      await endWire(reverse ? "raw" : "merge", reverse ? "output" : "input");
      await expect(graph.locator(".react-flow__edge")).toHaveCount(wireCount + 1);
      await expect(graph.locator(".is-compatible, .is-incompatible")).toHaveCount(0);
      await openPipelineSettings(editor, "Component");
      await editor.getByRole("button", { name: "Disconnect raw from merge", exact: true }).click();
      // The inspector remains an equivalent keyboard authoring route.
      await upstream.selectOption("raw");
      await editor
        .getByRole("button", { name: "Validate", exact: true })
        .click();
      await expect(
        editor.getByRole("heading", {
          name: "Valid processing graph",
          exact: true,
        }),
      ).toBeVisible();
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
      await editor
        .getByRole("button", { name: "Save draft", exact: true })
        .click();
      await expect(
        editor.getByText("Draft saved.", { exact: true }),
      ).toBeVisible();
      await page.reload();
      await openPipelineSettings(editor, "Component");
      await expect(node("raw")).toContainText("Raw reference");
      await expect(node("raw")).toContainText("Pass through");
      await page
        .getByRole("button", { name: "Application menu", exact: true })
        .click();
      await page
        .getByRole("menuitem", { name: "Settings", exact: true })
        .click();
      await page.getByRole("radio", { name: "Dark", exact: true }).check();
      await page
        .getByRole("button", { name: "Close settings", exact: true })
        .click();
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
        editor.getByRole("textbox", { name: "Node title", exact: true }),
      ).toHaveValue("Raw reference");
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: testInfo.outputPath(`visual-language-${strategy}-mobile.png`),
        fullPage: true,
      });
    } finally {
      const current = await page.request.get(endpoint, { headers });
      expect(current.ok(), await current.text()).toBe(true);
      const latest = (await current.json()) as PipelineView;
      const archived = await page.request.patch(endpoint, {
        headers,
        data: {
          expected_version: latest.version,
          name: latest.name,
          description: latest.description,
          archived: true,
        },
      });
      expect(archived.ok(), await archived.text()).toBe(true);
    }
  });
}

test.describe("touch connection dots", () => {
  test.use({ hasTouch: true });

  test("connects in two taps on a phone without opening settings", async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/?create=monitoring");
    const graph = page.getByLabel("Pipeline graph", { exact: true });
    await openPipelineSettings(page, "Component");
    await page.getByRole("combobox", { name: "Selected component", exact: true }).selectOption("detector");
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
    await page.getByRole("button", { name: "Validate", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Valid processing graph", exact: true })).toBeVisible();
  });
});
