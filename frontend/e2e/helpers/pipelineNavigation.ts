import { expect, type Locator, type Page } from "@playwright/test";
import type { PipelineView } from "../../src/types/pipelines.generated";

export async function openPipelineSettings(scope: Page | Locator, panel: "Service" | "Component") {
  const button = scope.getByRole("button", { name: panel === "Service" ? "Learning settings" : "Component settings", exact: true });
  if (await button.getAttribute("aria-expanded") !== "true") await button.click();
}

export async function savePipelineTemplate(page: Page, name?: string, copy = false): Promise<PipelineView> {
  await page.getByRole("button", { name: "Save template", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Save monitoring template", exact: true });
  if (name) await dialog.getByRole("textbox", { name: "Template name", exact: true }).fill(name);
  const saved = page.waitForResponse((response) => {
    const path = new URL(response.url()).pathname;
    return response.request().method() === "POST" && path.endsWith("/monitors/pipelines")
      || response.request().method() === "PUT" && path.endsWith("/draft");
  });
  await dialog.getByRole("button", { name: copy ? "Save as new template" : /^(Save|Update) template$/, exact: true }).click();
  const response = await saved;
  expect(response.ok(), await response.text()).toBe(true);
  await expect(dialog).toBeHidden();
  return response.json() as Promise<PipelineView>;
}

export async function expectReadablePipeline(page: Page) {
  const graph = page.getByLabel("Pipeline graph", { exact: true });
  await expect.poll(() => graph.locator(".react-flow__viewport").evaluate((element) =>
    new DOMMatrix(getComputedStyle(element).transform).a,
  )).toBe(1);
  await expect(graph.locator(".pl-node-kind svg")).toHaveCount(0);
  await expect(graph.locator(".pl-node strong").first()).toHaveCSS("font-size", "16px");
}

export async function expectPipelineOverview(page: Page) {
  const graph = page.getByLabel("Pipeline graph", { exact: true });
  await expect
    .poll(() =>
      graph.locator(".react-flow__viewport").evaluate((viewport) => {
        const area = viewport.closest(".react-flow")!.getBoundingClientRect();
        const nodes = [...viewport.querySelectorAll(".react-flow__node")];
        return (
          nodes.length > 0 &&
          nodes.every((element) => {
            const bounds = element.getBoundingClientRect();
            return (
              bounds.left >= area.left - 1 &&
              bounds.right <= area.right + 1 &&
              bounds.top >= area.top - 1 &&
              bounds.bottom <= area.bottom + 1
            );
          })
        );
      }),
    )
    .toBe(true);
}

export async function fitPipelineOverview(page: Page) {
  await page
    .getByLabel("Pipeline graph", { exact: true })
    .getByRole("button", { name: "Fit entire graph", exact: true })
    .click();
  await expectPipelineOverview(page);
}

export async function locatePipelineSelection(page: Page) {
  const graph = page.getByLabel("Pipeline graph", { exact: true });
  await graph
    .getByRole("button", { name: "Locate selected component", exact: true })
    .click();
  await expect
    .poll(() =>
      graph
        .locator(".react-flow__viewport")
        .evaluate(
          (element) => new DOMMatrix(getComputedStyle(element).transform).a,
        ),
    )
    .toBeGreaterThanOrEqual(0.8);
}
