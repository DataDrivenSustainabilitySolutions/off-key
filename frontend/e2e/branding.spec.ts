import { expect, test } from "@playwright/test";
import { setAppearance } from "./helpers/appearance";

test("the brand returns to dashboard home and inverts with the chosen appearance", async ({ page }) => {
  await page.goto("/sources");
  const home = page.getByRole("link", { name: "Aberration home", exact: true });
  await expect(home).toHaveAttribute("href", "/");
  // Choose the opposite of the browser preference as well as its matching theme.
  for (const theme of ["Light", "Dark"] as const) {
    await setAppearance(page, theme);
    await expect(home).toHaveCSS("color", theme === "Light" ? "rgb(0, 0, 0)" : "rgb(255, 255, 255)");
    await expect(home.locator("use")).toHaveAttribute("href", "/brand/logo.svg#mark");
    const bounds = await home.boundingBox();
    expect(bounds?.width).toBeGreaterThanOrEqual(44);
    expect(bounds?.height).toBeGreaterThanOrEqual(44);
  }
  for (const route of ["/sources", "/anomalies", "/account"]) {
    await page.getByRole("navigation", { name: "Primary navigation", exact: true }).waitFor();
    if (new URL(page.url()).pathname !== route) await page.goto(route);
    const beforeHome = await page.evaluate(() => performance.timeOrigin);
    await home.focus();
    await expect(home).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole("heading", { name: "Monitoring", exact: true })).toBeVisible();
    expect(await page.evaluate(() => performance.timeOrigin)).toBe(beforeHome);
  }
  await setAppearance(page, "Follow system");
});
