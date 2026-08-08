import { expect, test } from "@playwright/test";
import { connectAsync, type MqttClient } from "mqtt";

const publish = async (
  client: MqttClient,
  topic: string,
  value: number,
  timestamp: string,
) => {
  const payload = JSON.stringify({
    timestamp,
    value,
  });
  await client.publishAsync(topic, payload, { qos: 0, retain: false });
};

type InputTimestamps = Record<"L1" | "L2", string>;

const publishCycle = async (
  client: MqttClient,
  topics: InputTimestamps,
  index: number,
  l1Time: number = Date.now(),
): Promise<InputTimestamps> => {
  const inputTimestamps = {
    L1: new Date(l1Time).toISOString(),
    L2: new Date(l1Time + 75).toISOString(),
  };
  await publish(
    client,
    topics.L1,
    index === 35 ? 100 : 1 + index / 100,
    inputTimestamps.L1,
  );
  await publish(
    client,
    topics.L2,
    index === 35 ? 50 : 2 + index / 100,
    inputTimestamps.L2,
  );
  return inputTimestamps;
};

interface ChartEvidence {
  service_id: string;
  timestamp: string;
  strategy: string;
  anomaly_score: number | null;
  threshold: number;
  input_timestamps: InputTimestamps;
}

test.describe("adaptive monitoring production lifecycle", () => {
  test.setTimeout(600_000);

  test("correlates delayed multivariate evidence without moving the chart viewport", async ({
    page,
    playwright,
  }) => {
    const chargerId = `adaptive-e2e-${Date.now()}`;
    const topics = {
      L1: `charger/${chargerId}/live-telemetry/L1`,
      L2: `charger/${chargerId}/live-telemetry/L2`,
    };
    let serviceId: string | undefined;
    let authToken: string | null = null;
    let publisher: MqttClient | undefined;
    let eventTimeCursor = Date.now();
    const api = await playwright.request.newContext({
      baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:5173",
      timeout: 210_000,
    });

    try {
      const activePublisher = await connectAsync(
        process.env.MQTT_SOURCE_URL ?? "mqtt://127.0.0.1:1883",
        { clientId: `playwright-${chargerId}` },
      );
      publisher = activePublisher;
      await page.goto(`/monitoring/${chargerId}`);
      authToken = await page.evaluate(() => localStorage.getItem("auth_token"));
      expect(authToken).toBeTruthy();
      const expectedTelemetryTypes = ["L1", "L2"] as const;
      await publishCycle(activePublisher, topics, 0);
      const readTelemetryTypes = async () => {
        const response = await api.get(`/api/v1/telemetry/${chargerId}/type`, {
          headers: { Authorization: `Bearer ${authToken}` },
        });
        return (await response.json() as string[]).sort();
      };
      const hasExpectedTelemetryTypes = (types: string[]) =>
        types.length === expectedTelemetryTypes.length &&
        expectedTelemetryTypes.every((type, index) => types[index] === type);
      let retryPublishIndex = 0;
      await expect.poll(async () => {
        const types = await readTelemetryTypes();
        if (!hasExpectedTelemetryTypes(types) && retryPublishIndex < 5) {
          eventTimeCursor = Math.max(Date.now(), eventTimeCursor + 100);
          retryPublishIndex += 1;
          await publishCycle(
            activePublisher,
            topics,
            retryPublishIndex,
            eventTimeCursor,
          );
        }
        return types;
      }, { timeout: 120_000, intervals: [1_000, 2_000, 3_000] }).toEqual(
        expectedTelemetryTypes,
      );
      await page.reload();

      await expect(page.getByText("L1", { exact: true }).first()).toBeVisible({
        timeout: 30_000,
      });
      await expect(page.getByText("L2", { exact: true }).first()).toBeVisible({
        timeout: 30_000,
      });
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

      const readServiceStatus = async () => {
        const response = await api.get(
          "/api/v1/monitors/all?active_only=true&include_docker_status=true",
          { headers: { Authorization: `Bearer ${authToken}` } },
        );
        const services = await response.json() as Array<{
          id: string;
          operational_status?: {
            stage?: string;
            message_count?: number;
          };
        }>;
        return services.find((service) => service.id === serviceId)
          ?.operational_status;
      };
      const publishNextCycle = async (index: number) => {
        eventTimeCursor = Math.max(Date.now(), eventTimeCursor + 100);
        return publishCycle(activePublisher, topics, index, eventTimeCursor);
      };

      const publishedCycles: InputTimestamps[] = [];
      await expect.poll(async () => (await readServiceStatus())?.stage, {
        timeout: 240_000,
        intervals: [1_000, 1_000, 2_000],
      }).toBe("waiting_for_data");

      for (let index = 0; index < 40; index += 1) {
        publishedCycles.push(await publishNextCycle(index));
      }
      await expect.poll(async () => {
        const status = await readServiceStatus();
        return {
          operational: status?.stage === "operational",
          allMessagesConsumed:
            (status?.message_count ?? 0) >= publishedCycles.length * 2,
        };
      }, { timeout: 120_000 }).toEqual({
        operational: true,
        allMessagesConsumed: true,
      });

      let operationalEvidence: ChartEvidence[] = [];
      const lastPublishedCycle = publishedCycles[publishedCycles.length - 1];
      if (!lastPublishedCycle) {
        throw new Error("No telemetry cycles were published");
      }
      await expect.poll(async () => {
        const response = await api.get(`/api/v1/monitors/evidence/chart?charger_id=${chargerId}&limit=2000`, {
          headers: { Authorization: `Bearer ${authToken}` },
        });
        operationalEvidence = (await response.json() as ChartEvidence[]).filter(
          (row) => row.service_id === serviceId,
        );
        return operationalEvidence.some((row) =>
          row.strategy === "adaptive_stream" &&
          Number.isFinite(row.anomaly_score) &&
          Number.isFinite(row.threshold) &&
          Date.parse(row.input_timestamps.L1) ===
            Date.parse(lastPublishedCycle.L1) &&
          Date.parse(row.input_timestamps.L2) ===
            Date.parse(lastPublishedCycle.L2));
      }, { timeout: 120_000 }).toBe(true);

      for (const row of operationalEvidence) {
        expect(Object.keys(row.input_timestamps).sort()).toEqual(["L1", "L2"]);
        const normalizedInputs = {
          L1: new Date(row.input_timestamps.L1).toISOString(),
          L2: new Date(row.input_timestamps.L2).toISOString(),
        };
        expect(publishedCycles).toContainEqual(normalizedInputs);
        expect(Date.parse(row.timestamp)).toBe(
          Math.max(
            Date.parse(row.input_timestamps.L1),
            Date.parse(row.input_timestamps.L2),
          ),
        );
      }

      await page.goto(`/details/${chargerId}`);
      const l1Card = page.locator('[data-slot="card"]').filter({ hasText: "L1" }).first();
      const l2Card = page.locator('[data-slot="card"]').filter({ hasText: "L2" }).first();
      await expect(l1Card.getByText("Adaptive scores")).toBeVisible({ timeout: 60_000 });
      await expect(l2Card.getByText("Adaptive scores")).toBeVisible({ timeout: 60_000 });
      await l1Card.getByRole("button", { name: "Zoom in" }).click();
      await expect(l1Card.getByRole("button", { name: "Return to live" })).toBeVisible();

      eventTimeCursor = Math.max(Date.now() + 1_000, eventTimeCursor + 100);
      const pendingL1 = new Date(eventTimeCursor).toISOString();
      await publish(activePublisher, topics.L1, 123, pendingL1);
      await expect.poll(async () => {
        const response = await api.get(
          `/api/v1/telemetry/${chargerId}/data?type=L1&limit=1000`,
          { headers: { Authorization: `Bearer ${authToken}` } },
        );
        const rows = await response.json() as Array<{ timestamp: string }>;
        return rows.some((row) => Date.parse(row.timestamp) === Date.parse(pendingL1));
      }, { timeout: 60_000 }).toBe(true);

      const telemetryRefresh = page.waitForResponse((response) => {
        const url = new URL(response.url());
        return url.pathname.includes(`/v1/telemetry/${chargerId}/data`) &&
          url.searchParams.get("type") === "L1" &&
          url.searchParams.has("after_created");
      });
      await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
      await telemetryRefresh;
      await expect(l1Card.getByText("1 awaiting score")).toBeVisible();

      const pendingL2 = new Date(Date.parse(pendingL1) + 75).toISOString();
      await publish(activePublisher, topics.L2, 456, pendingL2);
      let delayedEvidence: ChartEvidence | undefined;
      await expect.poll(async () => {
        const response = await api.get(`/api/v1/monitors/evidence/chart?charger_id=${chargerId}&limit=2000`, {
          headers: { Authorization: `Bearer ${authToken}` },
        });
        const rows = await response.json() as ChartEvidence[];
        delayedEvidence = rows.find((row) =>
          row.service_id === serviceId &&
          Date.parse(row.input_timestamps.L1) === Date.parse(pendingL1) &&
          Date.parse(row.input_timestamps.L2) === Date.parse(pendingL2));
        return delayedEvidence !== undefined;
      }, { timeout: 120_000 }).toBe(true);
      expect(Date.parse(delayedEvidence!.timestamp)).toBe(Date.parse(pendingL2));

      await expect.poll(async () => {
        const response = await api.get(`/api/v1/telemetry/${chargerId}/data?type=L2&limit=1000`, {
          headers: { Authorization: `Bearer ${authToken}` },
        });
        const rows = await response.json() as Array<{ timestamp: string }>;
        return rows.some((row) => Date.parse(row.timestamp) === Date.parse(pendingL2));
      }, { timeout: 120_000 }).toBe(true);

      const evidenceRefresh = page.waitForResponse((response) => {
        const url = new URL(response.url());
        return url.pathname.includes("/v1/monitors/evidence/chart") &&
          url.searchParams.has("after_created");
      });
      const l2TelemetryRefresh = page.waitForResponse((response) => {
        const url = new URL(response.url());
        return url.pathname.includes(`/v1/telemetry/${chargerId}/data`) &&
          url.searchParams.get("type") === "L2" &&
          url.searchParams.has("after_created");
      });
      await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
      await Promise.all([evidenceRefresh, l2TelemetryRefresh]);
      await expect(l1Card.getByText("1 awaiting score")).toBeHidden();
      await expect(l1Card.getByRole("button", { name: "Return to live" })).toBeVisible();
      const scoreLabel = /^Anomaly score:/u;
      await expect(l1Card.getByText(scoreLabel)).toBeVisible({ timeout: 120_000 });
      await expect(l2Card.getByText(scoreLabel)).toBeVisible({ timeout: 120_000 });
    } finally {
      if (publisher) await publisher.endAsync();
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
