import { expect, test } from "@playwright/test";
import { connectAsync, type MqttClient } from "mqtt";

const telemetry = [
  ["voltageAc3", 233.3],
  ["voltageAc", 230.0],
  ["currentDc", 18.4],
  ["voltageAc2", 232.2],
  ["voltageAc1", 231.1],
] as const;

test.describe("device topic ingress", () => {
  test.setTimeout(180_000);

  test("discovers charger 0 and renders every canonical telemetry series", async ({
    page,
    playwright,
  }) => {
    let publisher: MqttClient | undefined;
    const api = await playwright.request.newContext({
      baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:5173",
      timeout: 120_000,
    });

    try {
      publisher = await connectAsync(
        process.env.MQTT_SOURCE_URL ?? "mqtt://127.0.0.1:1883",
        { clientId: `playwright-device-ingress-${Date.now()}` },
      );
      const timestamp = Date.now();
      for (const [telemetryType, value] of telemetry) {
        await publisher.publishAsync(
          `device/evCharger/0/${telemetryType}`,
          JSON.stringify({
            value,
            timestamp: new Date(timestamp).toISOString(),
          }),
          { qos: 1, retain: false },
        );
      }

      await page.goto("/");
      const authToken = await page.evaluate(() =>
        localStorage.getItem("auth_token"),
      );
      expect(authToken).toBeTruthy();
      const headers = { Authorization: `Bearer ${authToken}` };
      const expectedTypes = telemetry.map(([type]) => type).sort();

      await expect.poll(async () => {
        const response = await api.get("/api/v1/telemetry/0/type", { headers });
        if (!response.ok()) return [];
        return ((await response.json()) as string[]).sort();
      }).toEqual(expectedTypes);

      await expect.poll(async () => {
        const response = await api.get("/api/v1/chargers/available", { headers });
        if (!response.ok()) return false;
        const chargers = (await response.json()) as Array<{ charger_id: string }>;
        return chargers.some(({ charger_id }) => charger_id === "0");
      }).toBe(true);

      await page.reload();
      await expect(page.locator('a[href="/details/0"]').first()).toBeVisible();
      await page.goto("/details/0");
      await expect(page.getByRole("heading", { name: "Charger 0" })).toBeVisible();

      for (const title of [
        "Voltage Ac3",
        "Voltage Ac",
        "Current Dc",
        "Voltage Ac2",
        "Voltage Ac1",
      ]) {
        const card = page
          .locator('[data-slot="card"]')
          .filter({ has: page.getByText(title, { exact: true }) })
          .first();
        await expect(card.getByText(title, { exact: true })).toBeVisible();
        await card.scrollIntoViewIfNeeded();
        await expect(card.getByTestId("telemetry-echart")).toBeVisible();
      }
    } finally {
      await publisher?.endAsync();
      await api.dispose();
    }
  });
});
