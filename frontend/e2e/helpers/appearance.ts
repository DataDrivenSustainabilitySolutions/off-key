import { expect, type Page } from "@playwright/test";

/** Opens Preferences from the application menu and returns the dialog. */
export async function openPreferences(page: Page) {
  await page.getByRole("button", { name: "Application menu", exact: true }).click();
  await page.getByRole("menuitem", { name: "Preferences", exact: true }).click();
  return page.getByRole("dialog", { name: "Preferences", exact: true });
}

export async function setAppearance(page: Page, theme: "Light" | "Dark" | "Follow system") {
  const settings = await openPreferences(page);
  await settings.getByRole("radio", { name: theme, exact: true }).check();
  await settings.getByRole("button", { name: "Close preferences", exact: true }).click();
  await expect(settings).toHaveCount(0);
}
