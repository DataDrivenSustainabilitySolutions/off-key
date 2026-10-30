import { randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";
import type { PipelineCatalog, PipelineView } from "../src/types/pipelines.generated";
import { accessToken } from "./helpers/auth";
import { archivePipelines, openPipelineWorkspace } from "./helpers/pipelines";
import { openPipelineSettings, savePipelineTemplate } from "./helpers/pipelineNavigation";
import { expectNoHorizontalScroll } from "./helpers/layout";

for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
  test(`edits nested, adjacency and nullable parameters through the real API at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await openPipelineWorkspace(page);
    const headers = { Authorization: `Bearer ${await accessToken(page)}` };
    const response = await page.request.get("/api/v1/monitors/pipelines/catalog", { headers });
    expect(response.ok()).toBe(true);
    const catalog = await response.json() as PipelineCatalog;
    const definition = structuredClone(catalog.templates.find(item =>
      item.definition.strategy === "adaptive_stream")!.definition);
    const detector = definition.nodes!.find(node => node.kind === "detector")!;
    detector.component = "detector:aberrant_knn";
    detector.params = { k: 0, similarity_engine: { id: "faiss", params: { window_size: 0, warm_up: 0 } } };
    const created = await page.request.post("/api/v1/monitors/pipelines", {
      headers, data: { name: `Parameter controls ${randomUUID()}`, definition },
    });
    expect(created.ok(), await created.text()).toBe(true);
    const design = await created.json() as PipelineView;
    const endpoint = `/api/v1/monitors/pipelines/${design.id}`;
    try {
      await page.goto(`/?view=pipelines&pipeline=${design.id}`);
      await openPipelineSettings(page, "Component");
      await page.getByRole("combobox", { name: "Selected component", exact: true }).selectOption(detector.id);
      const validate = page.getByRole("button", { name: "Validate", exact: true });
      await validate.click();
      const k = page.getByRole("spinbutton", { name: "K", exact: true });
      const warm = page.getByRole("spinbutton", { name: "Warm Up", exact: true });
      const window = page.getByRole("spinbutton", { name: "Window Size", exact: true });
      await expect(k).toHaveAttribute("aria-invalid", "true");
      await expect(warm).toHaveAttribute("aria-invalid", "true");
      await expect(window).toHaveAttribute("aria-invalid", "true");
      await k.fill("2"); await warm.fill("3"); await window.fill("8");
      await validate.click();
      await expect(page.getByRole("heading", { name: "Valid processing graph", exact: true })).toBeVisible();
      const saved = await savePipelineTemplate(page);
      const published = await page.request.post(`${endpoint}/revisions`, {
        headers, data: { expected_version: saved.version },
      });
      expect(published.status(), await published.text()).toBe(201);

      // Publication changed the design version through the API; refresh before
      // continuing to save edits from the browser's optimistic version.
      await page.reload();
      await openPipelineSettings(page, "Component");
      await page.getByRole("combobox", { name: "Selected component", exact: true }).selectOption(detector.id);

      await page.getByRole("combobox", { name: "Detector model", exact: true })
        .selectOption("detector:aberrant_gadget_svm");
      await page.getByRole("checkbox", { name: "Automatic graph", exact: true }).uncheck();
      await page.getByRole("button", { name: "Add feature", exact: true }).click();
      await page.getByRole("button", { name: "Add feature", exact: true }).click();
      await page.getByRole("button", { name: "Add neighbor", exact: true }).first().click();
      await page.getByRole("spinbutton", { name: "Graph feature 0 neighbor 1", exact: true }).fill("1");
      await validate.click();
      await expect(page.getByRole("heading", { name: "Valid processing graph", exact: true })).toBeVisible();
      const adjacency = await savePipelineTemplate(page);
      expect(adjacency.draft.nodes!.find(node => node.id === detector.id)!.params!.graph)
        .toEqual({ "0": [1], "1": [] });

      await page.getByRole("combobox", { name: "Detector model", exact: true })
        .selectOption("detector:aberrant_x_stream");
      const cache = page.getByRole("spinbutton", { name: "Max Feature Cache Size", exact: true });
      await page.getByRole("checkbox", { name: "Max Feature Cache Size automatic", exact: true }).check();
      await expect(cache).toBeDisabled();
      await cache.locator("..").getByRole("button", { name: "Use default", exact: true }).click();
      await expect(cache).toBeEnabled();
      await expect(cache).toHaveValue("10000");
      await expectNoHorizontalScroll(page);
    } finally {
      await archivePipelines(page.request, headers, [endpoint]);
    }
  });
}
