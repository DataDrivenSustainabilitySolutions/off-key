import { expect, test, type Locator, type Page } from "@playwright/test";
import type { StorageStatus } from "../src/types/collection";

test.use({ locale: "en-US" });

async function openSettings(page: Page) {
  await page.getByRole("button", { name: "Application menu", exact: true }).click();
  await page.getByRole("menuitem", { name: "Preferences", exact: true }).click();
  return page.getByRole("dialog", { name: "Preferences", exact: true });
}

async function expectDialogFits(dialog: Locator) {
  expect(await dialog.evaluate(element => {
    const box = element.getBoundingClientRect();
    return box.left >= 0 && box.right <= innerWidth && box.top >= 0 && box.bottom <= innerHeight
      && element.scrollWidth <= element.clientWidth;
  })).toBe(true);
}

test("changes appearance without replacing the workspace and follows the device preference", async ({ page }, testInfo) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/sources");
  const search = page.getByRole("searchbox", { name: "Search catalogue", exact: true });
  await search.fill("settings keeps this search");
  // Keep a handle to the actual element to detect an accidental workspace remount.
  const originalSearch = await search.elementHandle();
  const location = page.url();
  const dialog = await openSettings(page);
  await expect(dialog.getByRole("tab", { name: "Appearance" })).toHaveAttribute("aria-selected", "true");
  await expect(dialog.getByText("Collection diagnostics", { exact: true })).toHaveCount(0);
  await expect(dialog.getByRole("radio")).toHaveCount(3);
  await expect(page).toHaveURL(location);

  for (const [label, value] of [["Dark", "dark"], ["Light", "light"]] as const) {
    await dialog.getByRole("radio", { name: label, exact: true }).check();
    await expect(page.locator("html")).toHaveClass(value);
    expect(await page.evaluate(() => localStorage.getItem("vite-ui-theme"))).toBe(value);
    await expectDialogFits(dialog);
    await dialog.screenshot({ path: testInfo.outputPath(`appearance-${value}.png`) });
  }

  await dialog.getByRole("radio", { name: "Light", exact: true }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(dialog.getByRole("radio", { name: "Dark", exact: true })).toBeChecked();
  await page.keyboard.press("ArrowRight");
  await expect(dialog.getByRole("radio", { name: "Follow system", exact: true })).toBeChecked();
  await expect(page.locator("html")).toHaveClass("light");
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(page.locator("html")).toHaveClass("dark");
  await dialog.getByRole("radio", { name: "Dark", exact: true }).check();
  await page.emulateMedia({ colorScheme: "light" });
  await expect(page.locator("html")).toHaveClass("dark");

  // Tab and Shift+Tab stay in the modal while its workspace is inert.
  await dialog.getByRole("button", { name: "Close preferences" }).focus();
  await page.keyboard.press("Tab");
  await expect(dialog.getByRole("tab", { name: "Appearance" })).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(dialog.getByRole("button", { name: "Close preferences" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Application menu", exact: true })).toBeFocused();
  await expect(search).toHaveValue("settings keeps this search");
  expect(await originalSearch!.evaluate(element => element.isConnected)).toBe(true);
  await expect(page).toHaveURL(location);
  await expect(page.getByTestId("navbar-actions").getByRole("button", { name: "Theme", exact: true })).toHaveCount(0);

  await page.reload();
  await expect(page.locator("html")).toHaveClass("dark");
  const reopened = await openSettings(page);
  await expect(reopened.getByRole("radio", { name: "Dark", exact: true })).toBeChecked();
  await reopened.getByRole("radio", { name: "Follow system", exact: true }).check();
  await reopened.getByRole("button", { name: "Close preferences" }).click();
  await page.reload();
  await expect(page.locator("html")).toHaveClass("light");
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(page.locator("html")).toHaveClass("dark");
  await originalSearch!.dispose();
});

test("keeps settings usable on small screens and across workspaces", async ({ page }, testInfo) => {
  for (const [path, width, height] of [["/", 320, 568], ["/anomalies", 390, 844], ["/account", 844, 390]] as const) {
    await page.setViewportSize({ width, height });
    await page.goto(path);
    const location = page.url();
    const dialog = await openSettings(page);
    await expectDialogFits(dialog);
    await dialog.getByRole("radio", { name: "Light", exact: true }).check();
    await dialog.getByRole("radio", { name: "Follow system", exact: true }).check();
    await dialog.getByRole("radio", { name: "Follow system", exact: true }).scrollIntoViewIfNeeded();
    await expect(dialog.getByRole("button", { name: "Close preferences" })).toBeInViewport();
    await expectDialogFits(dialog);
    await dialog.screenshot({ path: testInfo.outputPath(`appearance-${width}x${height}.png`) });
    if (path === "/anomalies") await page.mouse.click(2, 2);
    else await dialog.getByRole("button", { name: "Close preferences" }).click();
    await expect(dialog).toHaveCount(0);
    await expect(page).toHaveURL(location);
  }
});

test("shows real system diagnostics on their own page and keeps old links working", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Application menu", exact: true }).click();
  const storageReady = page.waitForResponse(response => new URL(response.url()).pathname === "/api/v1/system/storage");
  const healthReady = page.waitForResponse(response => new URL(response.url()).pathname === "/api/v1/system/health");
  await page.getByRole("menuitem", { name: "System status", exact: true }).click();
  await expect(page).toHaveURL(/\/system\/status$/);
  await expect(page.getByRole("heading", { name: "System status", exact: true })).toBeVisible();
  const storageResponse = await storageReady;
  const healthResponse = await healthReady;
  expect(storageResponse.ok(), await storageResponse.text()).toBe(true);
  expect(healthResponse.ok(), await healthResponse.text()).toBe(true);
  const status = await storageResponse.json() as StorageStatus;
  const gb = status.database_size_bytes >= 1_000_000_000;
  const size = (status.database_size_bytes / (gb ? 1_000_000_000 : 1_000_000))
    .toLocaleString("en-US", { maximumFractionDigits: 1 });
  await expect(page.getByText(`${size} ${gb ? "GB" : "MB"}`, { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Collection diagnostics", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Storage and retention", exact: true })).toBeVisible();

  const nextHealth = page.waitForResponse(response => new URL(response.url()).pathname === "/api/v1/system/health");
  expect((await nextHealth).ok()).toBe(true);
  const nextStorage = page.waitForResponse(response => new URL(response.url()).pathname === "/api/v1/system/storage");
  await page.getByRole("button", { name: "Refresh storage", exact: true }).click();
  expect((await nextStorage).ok()).toBe(true);
  await page.getByRole("button", { name: "Application menu", exact: true }).click();
  await expect(page.getByRole("menuitem", { name: "System status", exact: true })).toHaveAttribute("aria-current", "page");
  await page.keyboard.press("Escape");

  const dialog = await openSettings(page);
  await expect(dialog.getByRole("heading", { name: "Appearance", exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "Close preferences" }).click();
  await expect(page).toHaveURL(/\/system\/status$/);
  await page.goto("/account/settings");
  await expect(page).toHaveURL(/\/system\/status$/);
  await expect(page.getByRole("heading", { name: "System status", exact: true })).toBeVisible();
});
