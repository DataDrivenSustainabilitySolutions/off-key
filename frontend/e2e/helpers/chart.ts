import { expect, type Locator, type Page } from "@playwright/test";

export const zoomChart = async (page: Page, card: Locator) => {
  await card.scrollIntoViewIfNeeded();
  await card.getByTestId("telemetry-echart").hover({
    position: { x: 200, y: 100 },
  });
  await page.keyboard.down("Control");
  try {
    await page.mouse.wheel(0, -400);
  } finally {
    await page.keyboard.up("Control");
  }
  await expect(card.getByRole("button", { name: "Return to live" })).toBeVisible();
};
