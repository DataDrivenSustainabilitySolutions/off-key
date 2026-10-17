import { randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";
import type {
  PipelineCatalog,
  PipelineDefinition,
  PipelineView,
} from "../src/types/pipelines.generated";
import { loginPipelineWorkspace } from "./helpers/pipelines";
import {
  fitPipelineOverview,
  locatePipelineSelection,
} from "./helpers/pipelineNavigation";

test.beforeEach(async ({ page }) => loginPipelineWorkspace(page));

for (const strategy of ["static_baseline", "adaptive_stream"] as const) {
  test(`uses a consistent typed visual language for ${strategy}`, async ({
    page,
  }, testInfo) => {
    const token = await page.evaluate(() => localStorage.getItem("auth_token"));
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
      await page.setViewportSize({ width: 1600, height: 1000 });
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
      await expect(
        graph.getByLabel("Graph language", { exact: true }),
      ).toBeVisible();
      await expect(node("raw")).toContainText("Raw reference");
      await expect(node("raw")).toContainText("Pass through");
      const types = graph.getByRole("list", {
        name: "Connection data types",
        exact: true,
      });
      await expect(types).toContainText(
        strategy === "static_baseline" ? "P-values" : "Scores",
      );
      await expect(types).toContainText("Features");
      await expect(types).toContainText("Decisions");
      await expect(
        graph.getByTestId(`rf__edge-${JSON.stringify(["renamed", "merge"])}`),
      ).toHaveCount(1);
      await expect(
        graph.getByText("Features · input 2", { exact: true }),
      ).toBeVisible();
      await selector.selectOption("merge");
      await expect(
        editor.getByText(
          "Combine feature columns from the same aligned observation, in the order below.",
          { exact: true },
        ),
      ).toBeVisible();
      // Remove the first branch: stored order127 becomes visible input1, not input128.
      await editor
        .getByRole("button", { name: "Disconnect raw from merge", exact: true })
        .click();
      await expect(
        graph.getByText("Features · input 1", { exact: true }),
      ).toBeVisible();
      await expect(
        graph.getByText("Features · input 128", { exact: true }),
      ).toHaveCount(0);
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
      const ports = node("raw").locator(".pl-node-ports");
      for (const handle of ["input", "output"]) {
        const socket = node("raw").locator(`[data-handleid="${handle}"]`);
        const row = (await ports.boundingBox())!;
        const bounds = (await socket.boundingBox())!;
        expect(
          Math.abs(bounds.y + bounds.height / 2 - row.y - row.height / 2),
        ).toBeLessThan(3);
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
      await page.screenshot({
        path: testInfo.outputPath(`visual-language-${strategy}-dark.png`),
        fullPage: true,
      });
      await page.setViewportSize({ width: 390, height: 844 });
      await editor
        .getByRole("button", { name: "inspector", exact: true })
        .click();
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
