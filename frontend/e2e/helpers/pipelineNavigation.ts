import { expect, type Locator, type Page } from "@playwright/test";

export async function openPipelineSettings(scope: Page | Locator, panel: "Service" | "Component") {
  const button = scope.getByRole("button", { name: `${panel} settings`, exact: true });
  if (await button.getAttribute("aria-expanded") !== "true") await button.click();
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
