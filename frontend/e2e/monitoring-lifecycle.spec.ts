import { expect, test } from "@playwright/test";

import { registerVerifyAndLogin } from "./helpers/auth";

test.describe("monitoring lifecycle smoke", () => {
  test("starts and stops a RADAR workload from the monitoring page", async ({
    page,
    request,
  }) => {
    const chargerId = "e2e-smoke";
    let containerName: string | undefined;
    let authToken: string | null = null;

    try {
      await registerVerifyAndLogin(page);
      authToken = await page.evaluate(() => sessionStorage.getItem("auth_token"));
      await page.goto(`/monitoring/${chargerId}`);

      await expect(
        page.getByRole("heading", { name: `Charger ${chargerId}` })
      ).toBeVisible();

      await page.getByRole("combobox").first().selectOption("direct_patterns");
      await page.getByRole("button", { name: /all charger telemetry/i }).click();
      await expect(
        page.getByPlaceholder(/one topic per line/i)
      ).toHaveValue(`charger/${chargerId}/live-telemetry/#`);

      const startResponsePromise = page.waitForResponse(
        (response) =>
          response.url().includes("/v1/monitors/start") &&
          response.request().method() === "POST"
      );
      await page.getByRole("button", { name: /start monitoring/i }).click();

      const startResponse = await startResponsePromise;
      expect(startResponse.ok()).toBeTruthy();

      const startedService = (await startResponse.json()) as {
        service_id?: string;
        container_name?: string;
      };
      containerName = startedService.container_name;
      expect(containerName).toBeTruthy();
      expect(startedService.service_id).toBeTruthy();
      const serviceRow = page.getByRole("row").filter({ hasText: containerName! });
      await expect(serviceRow).toBeVisible({ timeout: 60_000 });

      const deletePath = `/v1/monitors/${encodeURIComponent(startedService.service_id!)}`;
      const stopResponsePromise = page.waitForResponse(
        (response) =>
          response.url().includes(deletePath) &&
          response.request().method() === "DELETE"
      );
      page.once("dialog", (dialog) => dialog.accept());
      await serviceRow
        .getByRole("button", { name: /stop and delete service/i })
        .click();

      const stopResponse = await stopResponsePromise;
      expect(stopResponse.ok()).toBeTruthy();
      await expect(page.getByText(/no active services/i)).toBeVisible({
        timeout: 30_000,
      });
      containerName = undefined;
    } finally {
      if (containerName && authToken) {
        await request.delete(
          `/api/v1/monitors/stop?container_name=${encodeURIComponent(containerName)}`,
          {
            failOnStatusCode: false,
            headers: { Authorization: `Bearer ${authToken}` },
          }
        );
      }
    }
  });
});
