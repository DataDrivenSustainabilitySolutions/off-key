import { expect, type Page } from "@playwright/test";
import { openPipelineSettings } from "./pipelineNavigation";

/** Verify actual screen/graph geometry, including zoom, before building branches. */
export async function dropPipelineComponent(page: Page, component: string, nodeId: string) {
  const close = page.getByRole("button", { name: "Close settings", exact: true });
  if (await close.count()) await close.click();
  await page.getByRole("button", { name: "Add component", exact: true }).click();
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
  // Drag events can round fractional screen coordinates. Measure the actual
  // pointer delivered to the canvas rather than assuming the requested target.
  await canvas.evaluate((element) => {
    element.addEventListener("drop", (event) => {
      const pointer = event as DragEvent;
      element.setAttribute("data-observed-drop", JSON.stringify({ x: pointer.clientX, y: pointer.clientY }));
    }, { once: true, capture: true });
  });
  const source = page.getByRole("button", { name: `Add ${component}`, exact: true });
  await source.scrollIntoViewIfNeeded();
  const item = (await source.boundingBox())!;
  await page.mouse.move(item.x + item.width / 2, item.y + item.height / 2);
  await page.mouse.down();
  // Start the native drag before moving into the area covered by the popover.
  // The menu becomes transparent to pointer events once a component is picked up.
  await page.mouse.move(item.x + item.width / 2 + 12, item.y + item.height / 2 + 12, { steps: 3 });
  await expect(page.locator(".pl-component-portal")).toHaveCSS("opacity", "0");
  await page.mouse.move(bounds.x + target.x, bounds.y + target.y, { steps: 5 });
  await page.mouse.up();
  const observed = await canvas.getAttribute("data-observed-drop");
  expect(observed, "The canvas must receive a real drop event").not.toBeNull();
  const pointer = JSON.parse(observed!) as { x: number; y: number };
  expect(Math.abs(pointer.x - bounds.x - target.x)).toBeLessThan(1);
  expect(Math.abs(pointer.y - bounds.y - target.y)).toBeLessThan(1);
  // The card is centred under the pointer, then its corner snaps to the grid.
  const card = await canvas.locator(".react-flow__node").first().evaluate((element) => ({
    width: (element as HTMLElement).offsetWidth, height: (element as HTMLElement).offsetHeight,
  }));
  const expected = {
    x: Math.round(((pointer.x - frame.x) / frame.zoom - card.width / 2) / 16) * 16,
    y: Math.round(((pointer.y - frame.y) / frame.zoom - card.height / 2) / 16) * 16,
  };
  const node = canvas.locator(`.react-flow__node[data-id="${nodeId}"]`);
  await page.getByRole("button", { name: "Close settings", exact: true }).click();
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
    // Cross the drag threshold before measuring movement; the initial gesture
    // activates dragging and is not part of the component's free displacement.
    await page.mouse.move(box.x + 24, box.y + 24);
    const initial = await position();
    await page.mouse.move(box.x + 24 + dx, box.y + 24 + dy, { steps: 5 });
    await page.mouse.up();
    return initial;
  };
  // Free placement retains the exact movement, rather than secretly snapping.
  await snap.click();
  await expect(snap).toHaveAttribute("aria-pressed", "false");
  const initial = await move(13, 17);
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
  await openPipelineSettings(page, "Component");
}
