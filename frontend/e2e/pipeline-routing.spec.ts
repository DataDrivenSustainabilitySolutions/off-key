import { savePipelineTemplate } from "./helpers/pipelineNavigation";
import { randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";
import type { PipelineCatalog, PipelineView } from "../src/types/pipelines.generated";
import { archivePipelines, openPipelineWorkspace } from "./helpers/pipelines";
import { fitPipelineOverview } from "./helpers/pipelineNavigation";
import { expectClearPipelineRouting, pipelineRoutingSnapshot } from "./helpers/pipelineRouting";
import { accessToken } from "./helpers/auth";

test("reroutes around moved components during native dragging and after reload", async ({ page }, testInfo) => {
  await openPipelineWorkspace(page);
  await page.setViewportSize({ width: 1600, height: 1100 });
  const token = await accessToken(page);
  const headers = { Authorization: `Bearer ${token}` };
  const response = await page.request.get("/api/v1/monitors/pipelines/catalog", { headers });
  expect(response.ok()).toBe(true);
  const catalog = await response.json() as PipelineCatalog;
  const definition = structuredClone(catalog.templates.find((item) => item.definition.strategy === "adaptive_stream")!.definition);
  definition.nodes!.push(
    { id: "middle", kind: "transform", component: "features.passthrough" },
    { id: "obstacle", kind: "transform", component: "features.passthrough" },
  );
  definition.edges = definition.edges!.filter((edge) => edge.target !== "detector");
  definition.edges.push({ source: "input", target: "middle" }, { source: "middle", target: "detector" });
  const created = await page.request.post("/api/v1/monitors/pipelines", { headers, data: {
    name: `Obstacle routing ${randomUUID()}`, definition,
    layout: { nodes: {
      input: { x: 0, y: 100 }, middle: { x: 360, y: 100 }, detector: { x: 900, y: 100 },
      policy: { x: 1220, y: 100 }, output: { x: 1540, y: 100 }, obstacle: { x: 650, y: 360 },
    } },
  } });
  expect(created.ok(), await created.text()).toBe(true);
  const pipeline = await created.json() as PipelineView;
  const endpoint = `/api/v1/monitors/pipelines/${pipeline.id}`;
  try {
    await page.goto(`/?pipeline=${pipeline.id}`);
    const graph = page.getByLabel("Pipeline graph", { exact: true });
    const node = (id: string) => graph.locator(`.react-flow__node[data-id="${id}"]`);
    const closeSettings = async () => {
      const close = page.getByRole("button", { name: "Close settings", exact: true });
      if (await close.count()) await close.click();
    };
    const position = (id: string) => node(id).evaluate((element) => {
      const matrix = new DOMMatrix(getComputedStyle(element).transform);
      return { x: matrix.e, y: matrix.f };
    });
    const move = async (id: string, x: number, y: number, verifyDuringDrag = true) => {
      await fitPipelineOverview(page);
      await node(id).click();
      await closeSettings();
      // Leave room for the new position as well as the existing diagram.
      await graph.getByRole("button", { name: "Zoom Out", exact: true }).click();
      await graph.getByRole("button", { name: "Zoom Out", exact: true }).click();
      const origin = await position(id);
      const zoom = await graph.locator(".react-flow__viewport").evaluate((element) => new DOMMatrix(getComputedStyle(element).transform).a);
      const box = (await node(id).boundingBox())!;
      const start = { x: box.x + box.width / 2, y: box.y + box.height / 2 - 15 * zoom };
      await page.mouse.move(start.x, start.y);
      await page.mouse.down();
      try {
        await page.mouse.move(start.x + 4, start.y + 4);
        await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));
        const pickedUp = await position(id);
        const frame = () => graph.locator(".react-flow__viewport").evaluate((element) => {
          const matrix = new DOMMatrix(getComputedStyle(element).transform);
          const area = element.closest(".react-flow")!.getBoundingClientRect();
          return { x: area.x + matrix.e, y: area.y + matrix.f, zoom: matrix.a };
        });
        const initialFrame = await frame();
        const grab = { x: (start.x + 4 - initialFrame.x) / initialFrame.zoom - pickedUp.x,
          y: (start.y + 4 - initialFrame.y) / initialFrame.zoom - pickedUp.y };
        for (let step = 1; step <= 5; step++) {
          const current = await frame();
          await page.mouse.move(current.x + (pickedUp.x + (x - pickedUp.x) * step / 5 + grab.x) * current.zoom,
            current.y + (pickedUp.y + (y - pickedUp.y) * step / 5 + grab.y) * current.zoom);
          if (verifyDuringDrag) await expectClearPipelineRouting(page);
        }
      } catch (error) {
        await testInfo.attach("drag-geometry", { body: JSON.stringify(await pipelineRoutingSnapshot(page)), contentType: "application/json" });
        throw error;
      } finally {
        await page.mouse.up();
      }
      await closeSettings();
      await expect.poll(() => position(id)).not.toEqual(origin);
      if (verifyDuringDrag) await expectClearPipelineRouting(page);
    };
    await expectClearPipelineRouting(page);
    await graph.getByRole("button", { name: "Snap to grid", exact: true }).click();
    const key = JSON.stringify(["middle", "detector"]);
    const initial = (await pipelineRoutingSnapshot(page)).paths[key];
    // An unrelated box now occupies an existing wire; the connection reroutes too.
    await move("obstacle", 650, 100);
    expect((await pipelineRoutingSnapshot(page)).paths[key]).not.toBe(initial);
    await page.screenshot({ path: testInfo.outputPath("routing-around-obstacle.png"), fullPage: true });
    // The middle of a chain moves up, down and behind its input.
    await move("middle", 360, -170);
    await move("middle", 360, 370);
    await move("middle", -340, 370);
    await move("middle", -340, 100);
    await page.screenshot({ path: testInfo.outputPath("routing-reversed-chain.png"), fullPage: true });
    // A blocked physical port is explicit, and recovers as soon as space returns.
    await move("middle", 100, 100, false);
    await expect(graph.getByRole("status")).toHaveText("Space components apart to show blocked connections.");
    expect((await pipelineRoutingSnapshot(page)).blocked.length).toBeGreaterThan(0);
    await move("middle", 360, 100, false);
    await expectClearPipelineRouting(page);
    await expect(graph.getByRole("status")).toHaveCount(0);
    await savePipelineTemplate(page);
    const saved = await page.request.get(endpoint, { headers });
    expect(saved.ok()).toBe(true);
    expect((await saved.json() as PipelineView).draft).toEqual(pipeline.draft);
    await page.reload();
    await expectClearPipelineRouting(page);
    await page.setViewportSize({ width: 390, height: 844 });
    await fitPipelineOverview(page);
    await expectClearPipelineRouting(page);
    await page.screenshot({ path: testInfo.outputPath("routing-phone.png"), fullPage: true });
  } finally {
    await archivePipelines(page.request, headers, [endpoint]);
  }
});
