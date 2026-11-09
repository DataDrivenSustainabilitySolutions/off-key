import { expect, test } from "@playwright/test";
import { setAppearance } from "./helpers/appearance";
import { installSidebarMockApi } from "./helpers/sidebarMockApi";

test.use({ storageState: { cookies: [], origins: [] } });

test("the brand returns to dashboard home and inverts with the chosen appearance", async ({ page }) => {
  await installSidebarMockApi(page);
  await page.goto("/sources");
  const sidebar = page.getByRole("complementary", { name: "Sidebar", exact: true });
  const home = sidebar.getByRole("link", { name: "Aberration home", exact: true });
  await expect(home).toHaveAttribute("href", "/");
  // Choose the opposite of the browser preference as well as its matching theme.
  for (const theme of ["Light", "Dark"] as const) {
    await setAppearance(page, theme);
    await expect(home).toHaveCSS("color", theme === "Light" ? "rgb(0, 0, 0)" : "rgb(255, 255, 255)");
    await expect(home.locator("use")).toHaveAttribute("href", "/brand/wordmark.svg#wordmark");
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
  // With the sidebar hidden, the bar that reopens it carries the brand mark home.
  await sidebar.getByRole("button", { name: "Hide sidebar", exact: true }).click();
  const mark = page.getByTestId("application-topbar").getByRole("link", { name: "Aberration home", exact: true });
  await expect(mark.locator("use")).toHaveAttribute("href", "/brand/logo.svg#mark");
  await page.getByRole("button", { name: "Show sidebar", exact: true }).click();
  await setAppearance(page, "Follow system");
});
