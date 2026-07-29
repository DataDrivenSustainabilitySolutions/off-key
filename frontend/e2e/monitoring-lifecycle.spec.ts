import { expect, test } from "@playwright/test";

test.describe("monitoring lifecycle smoke", () => {
  test.setTimeout(300_000);

  test("starts and stops a RADAR workload from the monitoring page", async ({
    page,
    playwright,
  }) => {
    const chargerId = "e2e-smoke";
    const topic = `charger/${chargerId}/live-telemetry/L1`;
    let serviceId: string | undefined;
    let containerName: string | undefined;
    let authToken: string | null = null;
    const cleanupRequest = await playwright.request.newContext({
      baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:5173",
      timeout: 210_000,
    });

    try {
      await page.goto(`/monitoring/${chargerId}`);
      authToken = await page.evaluate(() => localStorage.getItem("auth_token"));
      expect(authToken).toBeTruthy();

      await expect(
        page.getByRole("heading", { name: `Charger ${chargerId}` })
      ).toBeVisible();

      await page.getByRole("combobox").first().selectOption("direct_patterns");
      const topicPatternInput = page.getByRole("textbox");
      await topicPatternInput.fill(topic);
      await expect(topicPatternInput).toHaveValue(topic);

      await page
        .getByRole("button", { name: /show advanced settings/i })
        .click();
      await page
        .getByRole("button", { name: "About Betting method" })
        .hover();
      await expect(page.getByRole("tooltip")).toContainText(
        "Transforms each conformal p-value into a one-step e-value",
      );
      await page.getByRole("button", { name: /add tracker/i }).click();

      const secondTracker = page
        .getByRole("heading", { name: "Tracker 2" })
        .locator("..")
        .locator("..");
      await secondTracker.getByRole("textbox").fill("mixture-cusum");
      await secondTracker.getByRole("combobox").nth(0).selectOption("simple_mixture");
      await secondTracker.getByRole("combobox").nth(1).selectOption("cusum");
      await secondTracker.getByRole("spinbutton").nth(0).fill("25");
      await expect(page.getByText("2", { exact: true })).toBeVisible();

      const startResponsePromise = page.waitForResponse(
        (response) =>
          response.url().includes("/v1/monitors/start") &&
          response.request().method() === "POST"
      );
      await page.getByRole("button", { name: /start monitoring/i }).click();

      const startResponse = await startResponsePromise;
      expect(startResponse.ok()).toBeTruthy();

      const startPayload = startResponse.request().postDataJSON() as {
        static_baseline_config?: {
          martingale_config?: {
            trackers?: Array<Record<string, unknown>>;
          };
        };
      };
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
          threshold: 25,
        }),
      ]);

      const startedService = (await startResponse.json()) as {
        service_id?: string;
        container_name?: string;
      };
      serviceId = startedService.service_id;
      containerName = startedService.container_name;
      expect(serviceId).toBeTruthy();
      expect(containerName).toBeTruthy();
      const serviceRow = page.getByRole("row").filter({ hasText: containerName! });
      await expect(serviceRow).toBeVisible({ timeout: 60_000 });

      const stopResponsePromise = page.waitForResponse(
        (response) =>
          response.request().method() === "DELETE" &&
          new URL(response.url()).pathname.includes("/v1/monitors/"),
        { timeout: 240_000 }
      );
      page.once("dialog", (dialog) => dialog.accept());
      await serviceRow
        .getByRole("button", { name: /stop and delete service/i })
        .click();

      const stopResponse = await stopResponsePromise;
      expect(stopResponse.ok()).toBeTruthy();
      await expect(serviceRow).toBeHidden({ timeout: 60_000 });
      serviceId = undefined;
      containerName = undefined;
    } finally {
      if (serviceId && authToken) {
        await cleanupRequest.delete(`/api/v1/monitors/${encodeURIComponent(serviceId)}`, {
          failOnStatusCode: false,
          headers: { Authorization: `Bearer ${authToken}` },
        });
      } else if (containerName && authToken) {
        await cleanupRequest.delete(
          `/api/v1/monitors/stop?container_name=${encodeURIComponent(containerName)}`,
          {
            failOnStatusCode: false,
            headers: { Authorization: `Bearer ${authToken}` },
          }
        );
      }
      await cleanupRequest.dispose();
    }
  });
});
