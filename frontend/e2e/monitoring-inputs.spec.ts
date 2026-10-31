import { randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";
import { connectAsync, type MqttClient } from "mqtt";
import type { SystemSnapshot } from "../src/types/system";
import { addTestCharger } from "./helpers/collection";
import { accessToken } from "./helpers/auth";

test("offers only entities with fresh MQTT data and retains their exact broker context", async ({ page, playwright }, testInfo) => {
  // A fast reading keeps receiving for the 2 minute activity floor after it stops.
  test.setTimeout(300_000);
  const runId = randomUUID();
  const activeId = `active-${runId}`;
  const quietId = `quiet-${runId}`;
  const api = await playwright.request.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:5173", timeout: 120_000 });
  let token: string | null = null;
  let publisher: MqttClient | undefined;
  let existingConnections: Set<string> | undefined;
  const created: string[] = [];
  try {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Monitoring", exact: true })).toBeVisible();
    const create = page.getByRole("button", { name: "Create", exact: true });
    await expect(create).toBeEnabled();
    token = await accessToken(page);
    expect(token).toBeTruthy();
    const headers = { Authorization: `Bearer ${token}` };
    const readSystem = async (): Promise<SystemSnapshot> => {
      const response = await api.get("/api/v1/system", { headers });
      expect(response.ok(), await response.text()).toBeTruthy();
      return response.json();
    };
    existingConnections = new Set((await readSystem()).document.connections.map(connection => connection.id));
    publisher = await connectAsync(process.env.MQTT_SOURCE_URL ?? "mqtt://127.0.0.1:1884", { clientId: `monitoring-inputs-${runId}` });
    // Store this value before the collector subscribes, so it arrives as a retained snapshot.
    await publisher.publishAsync(`tests/${quietId}/temperature`, "25", { qos: 1, retain: true });
    created.push(activeId);
    await addTestCharger(api, token!, activeId, activeId, ["temperature", "voltage"]);
    created.push(quietId);
    await addTestCharger(api, token!, quietId, quietId, ["temperature"]);
    const initial = await readSystem();
    const activeReading = initial.document.streams.find(stream => stream.device_id === activeId && stream.label === "temperature")!;
    const quietReading = initial.document.streams.find(stream => stream.device_id === quietId)!;
    const broker = initial.document.connections.find(connection => connection.id === activeReading.connection_id)!;
    await publisher.publishAsync(activeReading.topic, "26", { qos: 1 });
    await expect.poll(async () => (await readSystem()).runtime.ingress?.readings?.[activeReading.id]?.fresh_received_at).toBeTruthy();
    expect((await readSystem()).runtime.ingress?.readings?.[quietReading.id]).toBeUndefined();

    await page.reload();
    await expect(create).toBeEnabled();
    await create.click();
    await expect(page.getByRole("button", { name: "Create service", exact: true })).toHaveCount(0);
    const picker = page.getByRole("button", { name: "Choose monitoring inputs", exact: true });
    await picker.click();
    const choices = page.getByRole("dialog", { name: "Choose monitoring inputs", exact: true });
    await choices.getByRole("searchbox", { name: "Search entities", exact: true }).fill(runId);
    const activeChoice = choices.getByRole("button").filter({ hasText: `${broker.label} / Entity ${activeId}` });
    const quietChoice = choices.getByRole("button").filter({ hasText: `${broker.label} / Entity ${quietId}` });
    await expect(activeChoice).toBeVisible();
    await expect(quietChoice).toHaveCount(0);
    await page.screenshot({ path: testInfo.outputPath("monitoring-receiving-inputs.png") });

    // A fresh receipt makes only this previously quiet entity available, without reopening the picker.
    await publisher.publishAsync(quietReading.topic, "27", { qos: 1 });
    await expect(quietChoice).toBeVisible({ timeout: 15_000 });
    await quietChoice.click();
    await expect(picker).toHaveText(`${broker.label} / Entity ${quietId}`);
    await picker.click();
    await choices.getByRole("searchbox", { name: "Search entities", exact: true }).fill(runId);
    await expect(choices.getByText("No matching inputs receiving data.", { exact: true })).toBeVisible({ timeout: 150_000 });
    await expect(picker).toHaveText(`${broker.label} / Entity ${quietId}`);
  } finally {
    if (publisher) {
      await publisher.publishAsync(`tests/${quietId}/temperature`, "", { qos: 1, retain: true });
      await publisher.endAsync();
    }
    if (token && created.length) {
      const headers = { Authorization: `Bearer ${token}` };
      const response = await api.get("/api/v1/system", { headers });
      expect(response.ok(), await response.text()).toBeTruthy();
      const snapshot = await response.json() as SystemSnapshot;
      const document = snapshot.document;
      document.streams = document.streams.filter(stream => !created.includes(stream.device_id ?? ""));
      document.devices = document.devices.filter(device => !created.includes(device.id));
      document.connections = document.connections.filter(connection => connection.id !== "test-broker" || connection.host !== "source-broker" || existingConnections?.has(connection.id)
        || document.streams.some(stream => stream.connection_id === connection.id)
        || document.devices.some(device => device.connection_id === connection.id));
      const saved = await api.put("/api/v1/system", { headers, data: { expected_revision: snapshot.revision, document } });
      expect(saved.ok(), await saved.text()).toBeTruthy();
    }
    await api.dispose();
  }
});
