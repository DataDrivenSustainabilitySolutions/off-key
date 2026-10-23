import { randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";

import { addTestCharger, removeTestCharger, fixtureEntityId, fixtureReadingKey } from "./helpers/collection";
import { accessToken } from "./helpers/auth";

test.describe("monitoring lifecycle smoke", () => {
  test.setTimeout(300_000);

  test("starts and stops a static monitor from the create form", async ({
    page,
    playwright,
  }) => {
    const deviceId = randomUUID();
    const chargerId = fixtureEntityId(deviceId);
    const topic = `telemetry/${chargerId}/${fixtureReadingKey(deviceId, "L1")}`;
    let serviceId: string | undefined;
    let authToken: string | null = null;
    const cleanupRequest = await playwright.request.newContext({
      baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:5173",
      timeout: 210_000,
    });

    try {
      await page.goto("/");
      authToken = await accessToken(page);
      expect(authToken).toBeTruthy();
      await addTestCharger(cleanupRequest, authToken!, deviceId, deviceId, [
        "L1",
      ]);
      await page.goto(`/?create=monitoring&target=${encodeURIComponent(chargerId)}`);

      await expect(
        page.getByRole("heading", { name: "Create service", exact: true }),
      ).toBeVisible();
      await page.getByRole("button", { name: "Static baseline", exact: true }).click();
      await expect(page.getByRole("checkbox", { name: "L1", exact: true })).toBeChecked();

      await page
        .getByRole("button", { name: /show advanced settings/i })
        .click();
      await page.getByRole("button", { name: "About Betting method" }).hover();
      await expect(page.getByRole("tooltip")).toContainText(
        "Transforms each conformal p-value into a one-step e-value",
      );
      await page.getByRole("button", { name: /add tracker/i }).click();

      const secondTracker = page
        .getByRole("heading", { name: "Tracker 2" })
        .locator("..")
        .locator("..");
      await secondTracker.getByRole("textbox").fill("mixture-cusum");
      await secondTracker
        .getByRole("combobox")
        .nth(0)
        .selectOption("simple_mixture");
      await secondTracker.getByRole("combobox").nth(1).selectOption("cusum");
      await expect(secondTracker.getByRole("combobox").nth(2)).toHaveValue(
        "automatic",
      );
      await expect(page.getByText("2", { exact: true })).toBeVisible();

      const startResponsePromise = page.waitForResponse(
        (response) =>
          response.url().includes("/v1/monitors/start") &&
          response.request().method() === "POST",
      );
      await page.getByRole("button", { name: /start monitoring/i }).click();

      const startResponse = await startResponsePromise;
      expect(startResponse.ok()).toBeTruthy();

      const startPayload = startResponse.request().postDataJSON() as {
        mqtt_topics?: string[];
        static_baseline_config?: {
          martingale_config?: {
            trackers?: Array<Record<string, unknown>>;
          };
        };
      };
      expect(startPayload.mqtt_topics).toEqual([topic]);
      expect(
        startPayload.static_baseline_config?.martingale_config?.trackers,
      ).toEqual([
        expect.objectContaining({
          tracker_id: "primary",
          betting_function: "power",
          alarm_statistic: "restarted_martingale",
        }),
        expect.objectContaining({
          tracker_id: "mixture-cusum",
          betting_function: "simple_mixture",
          alarm_statistic: "cusum",
          threshold_config: { mode: "automatic" },
        }),
      ]);

      serviceId = ((await startResponse.json()) as { service_id?: string })
        .service_id;
      expect(serviceId).toBeTruthy();
      const details = page.getByRole("region", {
        name: "Monitoring service details",
        exact: true,
      });
      // The form opens the service once its pipeline activation created the workload.
      await expect(details).toBeVisible({ timeout: 240_000 });

      const stopResponsePromise = page.waitForResponse(
        (response) =>
          response.request().method() === "DELETE" &&
          new URL(response.url()).pathname.includes("/v1/monitors/"),
        { timeout: 240_000 },
      );
      await page
        .getByRole("button", { name: "Service actions", exact: true })
        .click();
      await page
        .getByRole("menuitem", { name: "Stop and remove service", exact: true })
        .click();
      await page
        .getByRole("dialog", { name: "Stop and remove service?", exact: true })
        .getByRole("button", { name: "Remove service", exact: true })
        .click();

      const stopResponse = await stopResponsePromise;
      expect(stopResponse.ok()).toBeTruthy();
      await expect(details).toBeHidden({ timeout: 60_000 });
      serviceId = undefined;
    } finally {
      if (serviceId && authToken) {
        await cleanupRequest.delete(
          `/api/v1/monitors/${encodeURIComponent(serviceId)}`,
          {
            failOnStatusCode: false,
            headers: { Authorization: `Bearer ${authToken}` },
          },
        );
      }
      if (authToken)
        await removeTestCharger(cleanupRequest, authToken, chargerId);
      await cleanupRequest.dispose();
    }
  });
});
