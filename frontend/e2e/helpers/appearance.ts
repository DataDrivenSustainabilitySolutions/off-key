import { expect, type Page } from "@playwright/test";

/** The account menu sits in the sidebar footer; a hidden sidebar or a closed phone drawer is opened first. */
async function openAccountMenu(page: Page) {
  const menu = page.getByRole("button", { name: "Account menu", exact: true });
  if (!await menu.isVisible()) await page.getByRole("button", { name: "Show sidebar", exact: true }).click();
  await menu.click();
}

/** Opens Preferences from the account menu and returns the settings overlay. */
export async function openPreferences(page: Page) {
  await openAccountMenu(page);
  await page.getByRole("menuitem", { name: "Preferences", exact: true }).click();
  return page.getByRole("dialog", { name: "Settings", exact: true });
}

/** Opens the catalogue section from the account menu and returns the settings overlay. */
export async function openCatalogueSettings(page: Page) {
  await openAccountMenu(page);
  await page.getByRole("menuitem", { name: "Catalogue", exact: true }).click();
  return page.getByRole("dialog", { name: "Settings", exact: true });
}

export async function setAppearance(page: Page, theme: "Light" | "Dark" | "Follow system") {
  const settings = await openPreferences(page);
  await settings.getByRole("radio", { name: theme, exact: true }).check();
  await settings.getByRole("button", { name: "Close settings", exact: true }).click();
  await expect(settings).toHaveCount(0);
}
