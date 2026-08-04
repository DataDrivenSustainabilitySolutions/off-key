import { expect, test } from "@playwright/test";

const publish = async (topic: string, value: number) => {
  const payload = JSON.stringify({
    timestamp: new Date().toISOString(),
    value,
  });
  const username = process.env.EMQX_DASHBOARD_USERNAME ?? "admin";
  const password = process.env.EMQX_DASHBOARD_PASSWORD;
  if (!password) {
    throw new Error("EMQX_DASHBOARD_PASSWORD is required for adaptive E2E publishing");
  }
  const response = await fetch(
    `${process.env.EMQX_API_URL ?? "http://localhost:18083"}/api/v5/publish`,
    {
      method: "POST",
      headers: {
        Authorization: `Basic ${Buffer.from(`${username}:${password}`).toString("base64")}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ topic, payload, qos: 0, retain: false }),
    },
  );
  if (!response.ok) {
    throw new Error(`EMQX publish failed (${response.status}): ${await response.text()}`);
  }
};

test.describe("adaptive monitoring production lifecycle", () => {
  test.setTimeout(360_000);

  test("starts the lane and observes operational score and threshold evidence", async ({
    page,
    playwright,
  }) => {
    const chargerId = `adaptive-e2e-${Date.now()}`;
    const topic = `charger/${chargerId}/live-telemetry/L1`;
    let serviceId: string | undefined;
    let authToken: string | null = null;
    const api = await playwright.request.newContext({
      baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:5173",
      timeout: 210_000,
    });

    try {
      await publish(topic, 1);
      await page.goto(`/monitoring/${chargerId}`);
      authToken = await page.evaluate(() => localStorage.getItem("auth_token"));
      expect(authToken).toBeTruthy();

      await expect(page.getByText("L1", { exact: true })).toBeVisible({ timeout: 30_000 });
      await page.getByRole("button", { name: /Adaptive streams/i }).click();
      await expect(page.getByText("Adaptive stream lifecycle")).toBeVisible();
      await page.getByLabel("Warm-up samples").fill("32");
      await page.getByLabel("Calibration samples").fill("1");

      const startResponsePromise = page.waitForResponse(
        (response) => response.url().includes("/v1/monitors/start") && response.request().method() === "POST",
      );
      await page.getByRole("button", { name: /start adaptive monitoring/i }).click();
      const startResponse = await startResponsePromise;
      expect(startResponse.ok()).toBeTruthy();
      const started = (await startResponse.json()) as { service_id: string };
      serviceId = started.service_id;

      await expect.poll(async () => {
        const response = await api.get("/api/v1/monitors/all?active_only=true&include_docker_status=true", {
          headers: { Authorization: `Bearer ${authToken}` },
        });
        const services = await response.json() as Array<{
          id: string;
          operational_status?: { stage?: string };
        }>;
        return services.find((service) => service.id === serviceId)?.operational_status?.stage;
      }, { timeout: 120_000 }).toMatch(/collecting_training|collecting_calibration/);

      for (let index = 0; index < 36; index += 1) {
        await publish(topic, index === 35 ? 100 : 1 + index / 100);
      }

      await expect.poll(async () => {
        const response = await api.get(`/api/v1/monitors/evidence?charger_id=${chargerId}`, {
          headers: { Authorization: `Bearer ${authToken}` },
        });
        const rows = await response.json() as Array<{
          strategy: string;
          anomaly_score: number | null;
          threshold: number;
        }>;
        return rows.some((row) =>
          row.strategy === "adaptive_stream" &&
          Number.isFinite(row.anomaly_score) &&
          Number.isFinite(row.threshold));
      }, { timeout: 120_000 }).toBe(true);

      await page.goto(`/details/${chargerId}`);
      await expect(page.getByText("Adaptive scores")).toBeVisible({ timeout: 60_000 });
    } finally {
      if (serviceId && authToken) {
        await api.delete(`/api/v1/monitors/${encodeURIComponent(serviceId)}`, {
          failOnStatusCode: false,
          headers: { Authorization: `Bearer ${authToken}` },
        });
      }
      await api.dispose();
    }
  });
});
