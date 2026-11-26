import { randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";
import type { PipelineCatalog, PipelineView } from "../src/types/pipelines.generated";
import { accessToken } from "./helpers/auth";
import { archivePipelines, openPipelineWorkspace } from "./helpers/pipelines";
import { expectValidPipeline, openPipelineSettings, savePipelineTemplate } from "./helpers/pipelineNavigation";
import { expectNoHorizontalScroll } from "./helpers/layout";

for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
  test(`edits invalid and nullable parameters through the real API at ${viewport.width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    await openPipelineWorkspace(page);
    const headers = { Authorization: `Bearer ${await accessToken(page)}` };
    const response = await page.request.get("/api/v1/pipeline-components", { headers });
    expect(response.ok()).toBe(true);
    const catalog = await response.json() as PipelineCatalog;
    const definition = structuredClone(catalog.templates.find(item =>
      item.id === "adaptive_stream")!.definition);
    const detector = definition.nodes!.find(node => node.kind === "detector")!;
    detector.component = "detector:aberrant_knn";
    detector.params = { k: 0, window_size: 0 };
    const created = await page.request.post("/api/v1/pipelines", {
      headers, data: { name: `Parameter controls ${randomUUID()}`, definition },
    });
    expect(created.ok(), await created.text()).toBe(true);
    const design = await created.json() as PipelineView;
    const endpoint = `/api/v1/pipelines/${design.id}`;
    try {
      await page.goto(`/?view=pipelines&pipeline=${design.id}`);
      await openPipelineSettings(page, "Component");
      await page.getByRole("combobox", { name: "Selected step", exact: true }).selectOption(detector.id);
      // Every edit is checked shortly after it is made; invalid settings are marked in place.
      const k = page.getByRole("spinbutton", { name: "K", exact: true });
      const window = page.getByRole("spinbutton", { name: "Window Size", exact: true });
      await expect(k).toHaveAttribute("aria-invalid", "true");
      await expect(window).toHaveAttribute("aria-invalid", "true");
      await expect(window).toHaveCSS("border-top-width", "1px");
      await expect(page.getByRole("button", { name: /^\d+\+? design issues?$/ })).toBeVisible();
      await k.scrollIntoViewIfNeeded();
      await page.screenshot({ path: testInfo.outputPath(`parameter-graph-errors-${viewport.width}.png`) });
      await k.fill("2"); await window.fill("8");
      await expectValidPipeline(page);
      const fixed = await savePipelineTemplate(page);
      expect(fixed.draft.nodes!.find(node => node.id === detector.id)!.params)
        .toMatchObject({ k: 2, window_size: 8 });

      await page.getByRole("combobox", { name: "Detector model", exact: true })
        .selectOption("detector:aberrant_xstream");
      // The settings that do not decide a detector's behavior wait under More settings.
      const cache = page.getByRole("spinbutton", { name: "Max Feature Cache Size", exact: true });
      await expect(cache).toBeHidden();
      await page.getByText("More settings", { exact: true }).click();
      await page.getByRole("checkbox", { name: "Max Feature Cache Size automatic", exact: true }).check();
      await expect(cache).toBeDisabled();
      await cache.locator("..").getByRole("button", { name: "Use default", exact: true }).click();
      await expect(cache).toBeEnabled();
      await expect(cache).toHaveValue("10000");
      await expectNoHorizontalScroll(page);
      await page.screenshot({ path: testInfo.outputPath(`parameter-graph-controls-${viewport.width}.png`) });

      // Publish after browser editing: publication advances the design version,
      // while a restored editing session deliberately retains its saved version.
      await page.getByRole("combobox", { name: "Detector model", exact: true }).selectOption("detector:aberrant_knn");
      await k.fill("2"); await window.fill("8");
      const saved = await savePipelineTemplate(page);
      const published = await page.request.post(`${endpoint}/revisions`, {
        headers, data: { expected_version: saved.version },
      });
      expect(published.status(), await published.text()).toBe(201);
    } finally {
      await archivePipelines(page.request, headers, [endpoint]);
    }
  });
}
