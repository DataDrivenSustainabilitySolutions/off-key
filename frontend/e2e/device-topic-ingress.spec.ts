import { randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";
import { connectAsync, type MqttClient } from "mqtt";

import { addTestCharger, removeTestCharger, fixtureEntityId, fixtureReadingId } from "./helpers/collection";
import { accessToken } from "./helpers/auth";

const telemetry = [
  ["voltageAc3", 233.3],
  ["voltageAc", 230.0],
  ["currentDc", 18.4],
  ["voltageAc2", 232.2],
  ["voltageAc1", 231.1],
] as const;

test.describe("device topic ingress", () => {
  test("collects catalog charger 0 under its application ID and renders selected series", async ({
    page,
    playwright,
  }) => {
    const deviceId = randomUUID();
    const chargerId = fixtureEntityId(deviceId);
    let publisher: MqttClient | undefined;
    let authToken: string | null = null;
    const api = await playwright.request.newContext({
      baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:5173",
      timeout: 120_000,
    });

    try {
      await page.goto("/");
      authToken = await accessToken(page);
      expect(authToken).toBeTruthy();
      const headers = { Authorization: `Bearer ${authToken}` };
      await addTestCharger(
        api,
        authToken!,
        deviceId,
        "0",
        telemetry.map(([key]) => key),
      );
      publisher = await connectAsync(
        process.env.MQTT_SOURCE_URL ?? "mqtt://127.0.0.1:1884",
        { clientId: `playwright-device-ingress-${Date.now()}` },
      );
      for (const [telemetryType, value] of telemetry) {
        await publisher.publishAsync(
          `tests/0/${telemetryType}`,
          JSON.stringify(value),
          { qos: 1, retain: false },
        );
      }

      const readingIds = telemetry.map(([type]) => fixtureReadingId(deviceId, type)).sort();

      await expect
        .poll(async () => {
          const recorded = await Promise.all(readingIds.map(async (readingId) => {
            const response = await api.get(
              `/api/v1/readings/${encodeURIComponent(readingId)}/measurements?limit=1`,
              { headers },
            );
            return response.ok() && ((await response.json()) as unknown[]).length > 0;
          }));
          return readingIds.filter((_, index) => recorded[index]);
        })
        .toEqual(readingIds);

      await expect
        .poll(async () => {
          const response = await api.get("/api/v1/devices?active=true", {
            headers,
          });
          if (!response.ok()) return undefined;
          const devices = (await response.json()) as Array<{
            id: string;
            reading_ids: string[];
          }>;
          return devices.find(({ id }) => id === deviceId)?.reading_ids.sort();
        })
        .toEqual(readingIds);

      await page.goto(`/details/${deviceId}`);
      // The page is titled by the catalogue label of the device.
      await expect(
        page.getByRole("heading", { name: `Device ${deviceId}` }),
      ).toBeVisible();

      for (const [title] of telemetry) {
        const card = page
          .locator('[data-slot="card"]')
          .filter({ has: page.getByText(title, { exact: true }) })
          .first();
        await expect(card.getByText(title, { exact: true })).toBeVisible();
        // Neighboring lazy charts can change height after the first scroll.
        await expect(async () => {
          await card.scrollIntoViewIfNeeded();
          await expect(card.getByTestId("telemetry-echart")).toBeVisible({
            timeout: 1_000,
          });
        }).toPass({ timeout: 30_000 });
      }
    } finally {
      await publisher?.endAsync();
      if (authToken) await removeTestCharger(api, authToken, chargerId);
      await api.dispose();
    }
  });
});
