import { randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";
import { connectAsync, type MqttClient } from "mqtt";
import type { SystemSnapshot } from "../src/features/spatial/systemTypes";
import { addTestCharger, removeTestCharger } from "./helpers/collection";

test.setTimeout(300_000);

test("records only an opted-in reading and restores its history in the mobile workspace", async ({ page, playwright }) => {
  const entityId = randomUUID();
  const localId = `ui-${randomUUID()}`;
  const keys = ["temperature", "current", "voltage"];
  const api = await playwright.request.newContext({
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:5173", timeout: 120_000,
  });
  let token: string | null = null;
  let publisher: MqttClient | undefined;
  let serviceId: string | undefined;
  try {
    await page.goto("/");
    token = await page.evaluate(() => localStorage.getItem("auth_token"));
    expect(token).toBeTruthy();
    const headers = { Authorization: `Bearer ${token}` };
    // Start from a real main-format catalogue with every fixture reading Off.
    await addTestCharger(api, token!, entityId, localId, keys, { mode: "off", interval_seconds: 10 });
    const readSystem = async (): Promise<SystemSnapshot> => {
      const response = await api.get("/api/v1/system", { headers });
      expect(response.ok(), await response.text()).toBeTruthy();
      return response.json();
    };
    const initial = await readSystem();
    const stream = initial.document.streams.find(item => item.topic === `device/evCharger/${localId}/temperature`)!;
    expect(initial.runtime.bindings?.[stream.id]?.policy.mode).toBe("off");

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/sources");
    await expect(page.getByRole("dialog", { name: "Catalogue settings", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Import file", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Export catalogue", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Close settings", exact: true }).click();
    await page.getByRole("button", { name: "Open explorer", exact: true }).click();
    await page.getByRole("searchbox", { name: "Search catalogue", exact: true }).fill(`${entityId} temperature`);
    await page.getByRole("button", { name: "temperature, preview", exact: true }).click();
    const preview = page.getByRole("region", { name: "Reading preview", exact: true });
    await expect(preview).toBeVisible();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    const collection = preview.getByRole("region", { name: "Collection", exact: true });
    await collection.getByLabel("Collection mode", { exact: true }).selectOption("sample");
    await collection.getByLabel("Collection interval", { exact: true }).fill("1");
    expect((await readSystem()).runtime.collection_revision).toBe(initial.runtime.collection_revision);
    await collection.getByRole("button", { name: "Review change", exact: true }).click();
    await expect(collection.getByRole("button", { name: "Apply", exact: true })).toBeVisible();
    expect((await readSystem()).runtime.collection_revision).toBe(initial.runtime.collection_revision);
    await collection.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(collection.getByRole("button", { name: "Apply", exact: true })).toHaveCount(0);
    expect((await readSystem()).runtime.bindings?.[stream.id]?.policy.mode).toBe("off");
    await collection.getByRole("button", { name: "Review change", exact: true }).click();
    await collection.getByRole("button", { name: "Apply", exact: true }).click();
    await expect(preview.locator(".ex-preview-status")).toContainText("Recording", { timeout: 120_000 });
    const applied = await readSystem();
    expect(keys.map(key => {
      const reading = applied.document.streams.find(item => item.topic === `device/evCharger/${localId}/${key}`)!;
      return applied.runtime.bindings?.[reading.id]?.policy.mode;
    })).toEqual(["sample", "off", "off"]);
    const binding = applied.runtime.bindings![stream.id]!;
    // Main's stored identities survive the move to the generic collector.
    expect(binding.entity_id).toBe(entityId);
    expect(binding.telemetry_key).toBe("temperature");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await expect(page.getByRole("button", { name: "Connect", exact: true })).toHaveCount(0);
    publisher = await connectAsync(process.env.MQTT_SOURCE_URL ?? "mqtt://127.0.0.1:1884", { clientId: `ui-${entityId}` });
    for (const key of keys) await publisher.publishAsync(`device/evCharger/${localId}/${key}`, "25", { qos: 1 });
    await expect.poll(async () => {
      const response = await api.get(`/api/v1/telemetry/${entityId}/type`, { headers });
      return response.ok() ? response.json() : [];
    }).toEqual(["temperature"]);
    for (const key of keys) await publisher.publishAsync(`device/evCharger/${localId}/${key}`, "26", { qos: 1 });
    await expect.poll(async () => {
      const response = await api.get(`/api/v1/sources/state/${entityId}`, { headers });
      const states = (await response.json()) as Array<{ sensor_key: string; value: unknown }>;
      return states.map(({ sensor_key, value }) => ({ sensor_key, value }));
    }).toEqual([{ sensor_key: "temperature", value: 26 }]);

    // Background collection continues after the page has been left.
    await page.goto("/account");
    await publisher.publishAsync(`device/evCharger/${localId}/temperature`, "27", { qos: 1 });
    await expect.poll(async () => {
      const response = await api.get(`/api/v1/telemetry/${entityId}/data?type=temperature`, { headers });
      return (await response.json() as Array<{ value: number }>).some(point => point.value === 27);
    }).toBe(true);
    await page.goto(`/?reading=${encodeURIComponent(stream.id)}`);
    await expect(preview.locator(".ex-preview-value strong")).toHaveText("27");
    await expect(preview.locator('.ex-preview-chart[role="img"]')).toBeVisible();
    await page.getByRole("button", { name: "Zoom in", exact: true }).click();
    await expect(page.getByRole("button", { name: "Full range", exact: true })).toBeEnabled();
    await page.getByRole("button", { name: "Full range", exact: true }).click();
    await expect(page.getByRole("button", { name: "Full range", exact: true })).toBeDisabled();
    const types = await api.get(`/api/v1/telemetry/${entityId}/type`, { headers });
    expect(await types.json()).toEqual(["temperature"]);

    await page.goto(`/?create=monitoring&reading=${encodeURIComponent(stream.id)}`);
    await expect(page.getByRole("region", { name: "Create monitoring service", exact: true })).toBeVisible();
    await page.getByRole("textbox", { name: "Service name", exact: true }).fill("Workspace monitor");
    await page.getByLabel("Warm-up samples", { exact: true }).fill("2");
    await page.getByLabel("Calibration samples", { exact: true }).fill("2");
    const startedResponse = page.waitForResponse(response => response.url().includes("/v1/monitors/start") && response.request().method() === "POST");
    await page.getByRole("button", { name: "Start adaptive monitoring", exact: true }).click();
    const started = await startedResponse;
    expect(started.ok(), await started.text()).toBeTruthy();
    serviceId = ((await started.json()) as { service_id: string }).service_id;
    await expect(page.getByRole("region", { name: "Monitoring service details", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Rename service", exact: true }).click();
    const serviceName = page.getByRole("textbox", { name: "Rename service", exact: true });
    await serviceName.fill("Saved workspace monitor");
    await serviceName.press("Enter");
    await expect(page.getByRole("button", { name: "Rename service", exact: true })).toHaveText("Saved workspace monitor");
    await page.getByRole("button", { name: "Add service to favourites", exact: true }).click();
    await page.reload();
    await expect(page.getByRole("button", { name: "Remove service from favourites", exact: true })).toBeVisible();
    await expect.poll(async () => {
      const response = await api.get("/api/v1/monitors/all?active_only=true&include_docker_status=true", { headers });
      const services = await response.json() as Array<{ id: string; display_name?: string; operational_status: { stage: string } }>;
      const service = services.find(item => item.id === serviceId);
      expect(service?.display_name).toBe("Saved workspace monitor");
      return service?.operational_status.stage;
    }, { timeout: 120_000, intervals: [1000] }).toBe("waiting_for_data");
    for (let index = 0; index < 7; index++) {
      await publisher.publishAsync(`device/evCharger/${localId}/temperature`, String(30 + index), { qos: 1 });
      await page.waitForTimeout(1100);
    }
    await expect.poll(async () => {
      const response = await api.get(`/api/v1/monitors/evidence?charger_id=${entityId}`, { headers });
      const evidence = await response.json() as Array<{ service_id: string; anomaly_score: number | null; threshold: number | null }>;
      return evidence.some(row => row.service_id === serviceId && row.anomaly_score !== null && row.threshold !== null);
    }).toBe(true);
    await page.getByRole("tab", { name: "Evidence", exact: true }).click();
    await expect(page.getByRole("button", { name: "Full range", exact: true })).toBeVisible();
    await page.getByRole("tab", { name: "Configuration", exact: true }).click();
    await page.getByRole("button", { name: "Stop and remove service", exact: true }).click();
    await page.getByRole("dialog", { name: "Stop and remove service?", exact: true }).getByRole("button", { name: "Remove service", exact: true }).click();
    await expect(page.getByRole("heading", { name: "No monitoring services", exact: true })).toBeVisible();
    serviceId = undefined;
  } finally {
    await publisher?.endAsync();
    if (token && serviceId) await api.delete(`/api/v1/monitors/${encodeURIComponent(serviceId)}`, { headers: { Authorization: `Bearer ${token}` } });
    if (token) await removeTestCharger(api, token, entityId);
    await api.dispose();
  }
});
