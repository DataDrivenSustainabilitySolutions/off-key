import { expect, type Page } from "@playwright/test";

/** Verify actual screen/graph geometry, including zoom, before building branches. */
export async function dropPipelineComponent(page: Page, component: string, nodeId: string) {
  const canvas = page.getByLabel("Pipeline graph", { exact: true });
  const snap = canvas.getByRole("button", { name: "Snap to grid", exact: true });
  await expect(snap).toHaveAttribute("aria-pressed", "true");
  const bounds = (await canvas.boundingBox())!;
  const frame = await canvas.locator(".react-flow__viewport").evaluate((element) => {
    const matrix = new DOMMatrix(getComputedStyle(element).transform);
    const area = element.closest(".react-flow")!.getBoundingClientRect();
    return { x: area.x + matrix.e, y: area.y + matrix.f, zoom: matrix.a };
  });
  const target = { x: 163, y: 127 };
  const expected = {
    x: Math.round((bounds.x + target.x - frame.x) / frame.zoom / 16) * 16,
    y: Math.round((bounds.y + target.y - frame.y) / frame.zoom / 16) * 16,
  };
  await page.getByRole("button", { name: `Add ${component}`, exact: true })
    .dragTo(canvas, { targetPosition: target });
  const node = canvas.locator(`.react-flow__node[data-id="${nodeId}"]`);
  await expect(node).toBeVisible();
  const dropped = (await node.boundingBox())!;
  expect(Math.abs(dropped.x - frame.x - expected.x * frame.zoom)).toBeLessThan(3);
  expect(Math.abs(dropped.y - frame.y - expected.y * frame.zoom)).toBeLessThan(3);
  const after = (await canvas.boundingBox())!;
  expect(Math.abs(after.x - bounds.x)).toBeLessThan(1);
  expect(Math.abs(after.y - bounds.y)).toBeLessThan(1);

  const position = () => node.evaluate((element) => {
    const matrix = new DOMMatrix(getComputedStyle(element).transform);
    return { x: matrix.e, y: matrix.f };
  });
  const move = async (dx: number, dy: number) => {
    const box = (await node.boundingBox())!;
    await page.mouse.move(box.x + 20, box.y + 20);
    await page.mouse.down();
    await page.mouse.move(box.x + 20 + dx, box.y + 20 + dy, { steps: 5 });
    await page.mouse.up();
  };
  // Free placement retains the exact movement, rather than secretly snapping.
  await snap.click();
  await expect(snap).toHaveAttribute("aria-pressed", "false");
  const initial = await position();
  await move(13, 17);
  await expect.poll(async () => {
    const current = await position();
    return Math.max(Math.abs(current.x - initial.x - 13 / frame.zoom),
      Math.abs(current.y - initial.y - 17 / frame.zoom));
  }).toBeLessThan(1.5 / frame.zoom);
  const free = await position();
  expect(Math.max(Math.abs(free.x - Math.round(free.x / 16) * 16),
    Math.abs(free.y - Math.round(free.y / 16) * 16))).toBeGreaterThan(1);
  // Re-enabling snapping also aligns an existing component during a move.
  await snap.click();
  await expect(snap).toHaveAttribute("aria-pressed", "true");
  await move(23, 31);
  await expect.poll(async () => {
    const current = await position();
    return Math.max(Math.abs(current.x - Math.round(current.x / 16) * 16),
      Math.abs(current.y - Math.round(current.y / 16) * 16));
  }).toBeLessThan(0.01);
}
