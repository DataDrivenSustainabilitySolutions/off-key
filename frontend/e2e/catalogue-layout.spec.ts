import { expect, test, type Locator } from "@playwright/test";
import { setAppearance } from "./helpers/appearance";

async function bounds(locator: Locator) {
  const box = await locator.boundingBox();
  expect(box).not.toBeNull();
  return box!;
}

test("the catalogue edge follows resizing and restores the full workspace when collapsed", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  const header = page.getByTestId("application-header");
  const main = page.locator(".app-catalogue-main");
  const sidebar = page.locator(".app-catalogue-sidebar");
  const search = page.getByRole("searchbox", { name: "Search catalogue", exact: true });
  const hide = page.getByRole("button", { name: "Hide catalogue", exact: true });
  const show = page.getByRole("button", { name: "Show catalogue", exact: true });
  const heading = page.getByRole("heading", { name: "Monitoring", exact: true });
  const navigation = page.getByRole("navigation", { name: "Primary navigation", exact: true });
  await expect(hide).toBeVisible();
  const initialHeader = await bounds(header);
  expect(initialHeader.height).toBe(64);
  await expect(header.locator(".catalogue-edge-toggle")).toHaveCount(0);
  expect((await bounds(main)).y).toBe(initialHeader.y + initialHeader.height);

  const edge = page.getByRole("separator", { name: "Resize explorer sidebar", exact: true });
  await edge.focus();
  await page.keyboard.press("Shift+ArrowRight");
  await expect(edge).toHaveAttribute("aria-valuenow", "352");
  await expect.poll(async () => (await bounds(sidebar)).width).toBe(352);
  const panel = await bounds(sidebar);
  const control = await bounds(hide);
  expect(control.x + control.width / 2).toBeCloseTo(panel.x + panel.width, 0);
  expect(control.width).toBeGreaterThanOrEqual(44);
  expect(control.height).toBeGreaterThanOrEqual(44);
  expect((await bounds(heading)).x - control.x - control.width).toBeGreaterThanOrEqual(24);

  await search.fill("preserve this catalogue search");
  const originalSearch = await search.elementHandle();
  await hide.click();
  await expect(show).toHaveAttribute("aria-expanded", "false");
  await expect(search).toBeHidden();
  await expect(sidebar).toHaveAttribute("inert", "");
  await expect.poll(async () => (await bounds(main)).width).toBe(1280);
  expect((await bounds(main)).x).toBe(0);
  expect(await bounds(header)).toEqual(initialHeader);
  for (const name of ["Monitoring", "Sources", "Reporting"]) {
    await expect(navigation.getByRole("link", { name, exact: true })).toBeVisible();
  }
  await show.focus();
  await page.keyboard.press("Enter");
  await expect(search).toHaveValue("preserve this catalogue search");
  expect(await originalSearch!.evaluate(element => element.isConnected)).toBe(true);
  await search.clear();
  await originalSearch!.dispose();
  await hide.click();
  await page.reload();
  await expect(show).toBeVisible();
  await show.focus();
  await page.keyboard.press("Enter");
  await expect.poll(async () => (await bounds(sidebar)).width).toBe(352);

  for (const appearance of ["Light", "Dark"] as const) {
    await setAppearance(page, appearance);
    await page.screenshot({ path: testInfo.outputPath(`catalogue-desktop-${appearance.toLowerCase()}.png`), animations: "disabled" });
    await hide.click();
    await expect.poll(async () => (await bounds(main)).width).toBe(1280);
    await page.screenshot({ path: testInfo.outputPath(`catalogue-collapsed-${appearance.toLowerCase()}.png`), animations: "disabled" });
    await show.click();
    await expect(search).toBeVisible();
  }
  await edge.focus();
  await page.keyboard.press("Home");
  await page.emulateMedia({ reducedMotion: "reduce" });
  expect(await page.locator(".app-catalogue-workspace").evaluate(element => parseFloat(getComputedStyle(element).transitionDuration))).toBeLessThanOrEqual(0.001);
  await setAppearance(page, "Follow system");
});

test("mobile drawers leave the header and content geometry intact and restore keyboard focus", async ({ page }, testInfo) => {
  for (const width of [320, 390, 760]) {
    await page.setViewportSize({ width, height: 844 });
    await page.goto("/");
    const header = page.getByTestId("application-header");
    const main = page.locator(".app-catalogue-main");
    const show = page.getByRole("button", { name: "Show catalogue", exact: true });
    const heading = page.getByRole("heading", { name: "Monitoring", exact: true });
    await expect(show).toBeVisible();
    const initialMain = await bounds(main);
    const initialHeader = await bounds(header);
    expect(initialHeader.height).toBe(112);
    expect(initialMain.y).toBe(initialHeader.y + initialHeader.height);
    expect(initialMain.width).toBe(width);
    const face = await bounds(show.locator(".catalogue-edge-face"));
    expect((await bounds(heading)).x - face.x - face.width).toBeGreaterThanOrEqual(16);
    await expect(page.getByRole("separator", { name: "Resize explorer sidebar", exact: true })).toHaveCount(0);

    await show.click();
    const drawer = page.getByRole("dialog", { name: "MQTT catalogue", exact: true });
    const close = drawer.getByRole("button", { name: "Hide catalogue", exact: true });
    await expect(drawer).toBeFocused();
    expect((await bounds(drawer)).y).toBe(initialHeader.y + initialHeader.height);
    expect(await bounds(main)).toEqual(initialMain);
    expect(await bounds(header)).toEqual(initialHeader);
    const closeBounds = await bounds(close);
    // Drawer translation can introduce subpixel rounding in bounding boxes.
    expect(closeBounds.width).toBeCloseTo(44, 2);
    expect(closeBounds.height).toBeCloseTo(44, 2);
    expect(closeBounds.x + closeBounds.width).toBeLessThanOrEqual(width);
    await close.focus();
    await page.keyboard.press("Tab");
    expect(await drawer.evaluate(element => element.contains(document.activeElement))).toBe(true);

    for (const appearance of ["Light", "Dark"] as const) {
      await page.keyboard.press("Escape");
      await expect(drawer).toHaveCount(0);
      await expect(show).toBeFocused();
      await setAppearance(page, appearance);
      await show.click();
      await expect(drawer).toBeVisible();
      if (width === 390) await page.screenshot({ path: testInfo.outputPath(`catalogue-mobile-${appearance.toLowerCase()}.png`), animations: "disabled" });
    }
    await close.click();
    await expect(drawer).toHaveCount(0);
    await expect(show).toBeFocused();
    await page.keyboard.press("ControlOrMeta+k");
    await expect(drawer.getByRole("searchbox", { name: "Search catalogue", exact: true })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(drawer).toHaveCount(0);
    await expect(show).toBeFocused();
    await show.click();
    await page.mouse.click(width - 4, initialHeader.y + initialHeader.height + 80);
    await expect(drawer).toHaveCount(0);
    await expect(show).toBeFocused();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await setAppearance(page, "Follow system");
  }

  await page.setViewportSize({ width: 1024, height: 800 });
  await expect(page.getByRole("button", { name: "Hide catalogue", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Hide catalogue", exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Show catalogue", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "MQTT catalogue", exact: true })).toBeVisible();
  await page.setViewportSize({ width: 1024, height: 800 });
  await expect(page.getByRole("dialog", { name: "MQTT catalogue", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Show catalogue", exact: true })).toBeFocused();
  await expect(page.getByRole("navigation", { name: "System explorer", exact: true })).toBeHidden();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("dialog", { name: "MQTT catalogue", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Show catalogue", exact: true })).toBeVisible();
});
