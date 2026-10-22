import { expect, type Page } from "@playwright/test";

export async function setAppearance(page: Page, theme: "Light" | "Dark" | "Follow system") {
  await page.getByRole("button", { name: "Application menu", exact: true }).click();
  await page.getByRole("menuitem", { name: "Preferences", exact: true }).click();
  const settings = page.getByRole("dialog", { name: "Preferences", exact: true });
  await settings.getByRole("radio", { name: theme, exact: true }).check();
  await settings.getByRole("button", { name: "Close preferences", exact: true }).click();
  await expect(settings).toHaveCount(0);
}
