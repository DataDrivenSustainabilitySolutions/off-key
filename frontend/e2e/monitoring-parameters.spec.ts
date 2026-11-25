import { randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";
import { accessToken } from "./helpers/auth";
import { addTestCharger, fixtureTarget, removeTestCharger } from "./helpers/collection";
import { expectNoHorizontalScroll } from "./helpers/layout";

test("setup controls retain typed values and display real API field errors on desktop and mobile", async ({ page, playwright }, testInfo) => {
  test.setTimeout(300_000);
  const device = randomUUID();
  const api = await playwright.request.newContext({
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:5173", timeout: 210_000,
  });
  let token: string | null = null;
  let serviceId: string | undefined;
  try {
    await page.goto("/");
    token = await accessToken(page);
    await addTestCharger(api, token!, device, device, ["L1", "L2"]);
    await page.goto(`/?create=monitoring&target=${encodeURIComponent(fixtureTarget(device))}`);
    await page.getByRole("button", { name: "Adaptive stream", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Configure adaptive monitoring", exact: true })).toBeVisible();
    const model = page.getByRole("combobox", { name: "Model", exact: true });
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      await model.selectOption("aberrant_xstream");
      // The settings that do not decide a detector's behavior wait under More settings.
      await page.getByText("More settings", { exact: true }).click();
      const cache = page.getByRole("spinbutton", { name: "Max Feature Cache Size", exact: true });
      await page.getByRole("checkbox", { name: "Max Feature Cache Size automatic", exact: true }).check();
      await expect(cache).toBeDisabled();
      await cache.locator("..").getByRole("button", { name: "Use default", exact: true }).click();
      await expect(cache).toBeEnabled();
      await model.selectOption("aberrant_knn");
      // More neighbors than the window holds: only the API knows the two belong together.
      const k = page.getByRole("spinbutton", { name: "K", exact: true });
      await k.fill("10");
      await page.getByRole("spinbutton", { name: "Window Size", exact: true }).fill("8");
      await page.getByLabel("Warm-up samples", { exact: true }).fill("8");
      await page.getByLabel("Calibration samples", { exact: true }).fill("2");
      const rejected = page.waitForResponse(response => response.request().method() === "POST"
        && new URL(response.url()).pathname.endsWith("/v1/monitors"));
      await page.getByRole("button", { name: "Start adaptive monitoring", exact: true }).click();
      const response = await rejected;
      expect(response.status(), await response.text()).toBe(422);
      const errors = await response.json() as { detail: { loc: (string | number)[] }[] };
      expect(errors.detail.some(issue => issue.loc.at(-1) === "k")).toBe(true);
      await expect(k).toHaveAttribute("aria-invalid", "true");
      await expect(k).toHaveCSS("border-top-width", "1px");
      await k.scrollIntoViewIfNeeded();
      await expectNoHorizontalScroll(page);
      await page.screenshot({ path: testInfo.outputPath(`parameter-form-errors-${width}.png`) });
    }
    await page.getByRole("spinbutton", { name: "K", exact: true }).fill("4");
    const accepted = page.waitForResponse(response => response.request().method() === "POST"
      && new URL(response.url()).pathname.endsWith("/v1/monitors"));
    await page.getByRole("button", { name: "Start adaptive monitoring", exact: true }).click();
    const response = await accepted;
    expect(response.ok(), await response.text()).toBe(true);
    const request = response.request().postDataJSON();
    expect(request.monitoring.model_params).toMatchObject({ k: 4, window_size: 8 });
    serviceId = (await response.json() as { monitor_id: string }).monitor_id;
    await expect(page.getByRole("region", { name: "Monitoring service details", exact: true })).toBeVisible({ timeout: 240_000 });
  } finally {
    if (serviceId && token) await api.delete(`/api/v1/monitors/${serviceId}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (token) await removeTestCharger(api, token, device);
    await api.dispose();
  }
});
