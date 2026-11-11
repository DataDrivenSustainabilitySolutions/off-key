import { expect, test } from "@playwright/test";
import { setAppearance } from "./helpers/appearance";
import { installSidebarMockApi } from "./helpers/sidebarMockApi";

test.use({ storageState: { cookies: [], origins: [] } });

test("the compact sidebar returns to Monitoring in either appearance without a wordmark", async ({ page }) => {
  await installSidebarMockApi(page);
  await page.goto("/sources");
  const sidebar = page.getByRole("complementary", { name: "Sidebar", exact: true });
  const home = sidebar.getByRole("link", { name: "Monitoring", exact: true });
  await expect(home).toHaveAttribute("href", "/");
  await expect(sidebar.getByRole("link", { name: "Aberration home", exact: true })).toHaveCount(0);
  // Choose the opposite of the browser preference as well as its matching theme.
  for (const theme of ["Light", "Dark"] as const) {
    await setAppearance(page, theme);
    await expect(page.locator("html")).toHaveClass(theme.toLowerCase());
    await expect(home).toBeVisible();
    const bounds = await home.boundingBox();
    expect(bounds?.height).toBeGreaterThanOrEqual(32);
  }
  for (const route of ["/sources", "/anomalies"]) {
    await sidebar.getByRole("navigation", { name: "Workspace", exact: true }).waitFor();
    if (new URL(page.url()).pathname !== route) await page.goto(route);
    const beforeHome = await page.evaluate(() => performance.timeOrigin);
    await home.focus();
    await expect(home).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole("heading", { name: "Monitoring", exact: true })).toBeVisible();
    expect(await page.evaluate(() => performance.timeOrigin)).toBe(beforeHome);
  }
  // Collapsing the sidebar leaves only its reopen control, with no branded bar.
  await sidebar.getByRole("button", { name: "Hide sidebar", exact: true }).click();
  await expect(page.getByRole("link", { name: "Aberration home", exact: true })).toHaveCount(0);
  await expect(page.getByRole("banner")).toHaveCount(0);
  await page.getByRole("button", { name: "Show sidebar", exact: true }).click();
  await setAppearance(page, "Follow system");
});
