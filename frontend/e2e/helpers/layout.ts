import { expect, type Locator, type Page } from "@playwright/test";

/** The dialog sits inside the viewport and does not scroll sideways. */
export async function expectDialogFits(dialog: Locator) {
  expect(await dialog.evaluate(element => {
    const box = element.getBoundingClientRect();
    return box.left >= 0 && box.right <= innerWidth && box.top >= 0 && box.bottom <= innerHeight
      && element.scrollWidth <= element.clientWidth;
  })).toBe(true);
}

export async function expectNoHorizontalScroll(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
}
