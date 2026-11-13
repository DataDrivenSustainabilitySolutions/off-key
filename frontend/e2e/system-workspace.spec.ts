import { randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";
import { connectAsync, type MqttClient } from "mqtt";
import type { SystemSnapshot } from "../src/types/system";
import { addTestCharger, removeTestCharger, waitForCollectionReady } from "./helpers/collection";
import { openCatalogueSettings, setAppearance } from "./helpers/appearance";
import { accessToken } from "./helpers/auth";
import { expectNoHorizontalScroll } from "./helpers/layout";

test.setTimeout(300_000);
// A missing UI control should fail with a trace before the enclosing CI step
// times out; infrastructure readiness keeps its explicit, longer assertions.
test.use({ locale: "en-US", actionTimeout: 30_000 });

test("records only an opted-in reading and restores its history in the mobile workspace", async ({ page, playwright }, testInfo) => {
  const deviceId = randomUUID();
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
    const workspaces = page.getByRole("navigation", { name: "Workspace", exact: true });
    await expect(workspaces.getByRole("link", { name: "Monitoring", exact: true })).toHaveAttribute("aria-current", "page");
    await expect(workspaces.getByRole("link", { name: "Sources", exact: true })).toBeVisible();
    await workspaces.getByRole("link", { name: "Reporting", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Reporting", exact: true })).toBeVisible();
    await expect(workspaces.getByRole("link", { name: "Reporting", exact: true })).toHaveAttribute("aria-current", "page");
    await page.getByRole("button", { name: "Account menu", exact: true }).click();
    await expect(page.getByRole("menuitem", { name: "Monitoring", exact: true })).toHaveCount(0);
    await expect(page.getByRole("menuitem", { name: "Entities", exact: true })).toHaveCount(0);
    await page.keyboard.press("Escape");
    await page.setViewportSize({ width: 390, height: 844 });
    // Phones open the same sidebar as a drawer, which closes once a workspace is chosen.
    await page.getByRole("button", { name: "Show sidebar", exact: true }).click();
    await workspaces.getByRole("link", { name: "Monitoring", exact: true }).click();
    await expect(page.getByRole("dialog", { name: "Navigation", exact: true })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Monitoring", exact: true })).toBeVisible();
    await page.setViewportSize({ width: 1280, height: 720 });
    token = await accessToken(page);
    expect(token).toBeTruthy();
    const headers = { Authorization: `Bearer ${token}` };
    // Start from a generic catalogue with every fixture reading Off.
    await addTestCharger(api, token!, deviceId, localId, keys, { mode: "off", interval_seconds: 10 });
    const readSystem = async (): Promise<SystemSnapshot> => {
      const response = await api.get("/api/v1/catalogue", { headers });
      expect(response.ok(), await response.text()).toBeTruthy();
      return response.json();
    };
    const initial = await readSystem();
    const stream = initial.document.readings.find(item => item.topic === `tests/${localId}/temperature`)!;
    expect(initial.runtime.bindings?.[stream.id]?.policy.mode).toBe("off");

    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole("button", { name: "Show sidebar", exact: true }).click();
    await workspaces.getByRole("link", { name: "Sources", exact: true }).click();
    await expect(page.getByRole("main", { name: "Sources workspace", exact: true })).toBeVisible();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await openCatalogueSettings(page);
    await expect(page.getByRole("button", { name: "Import JSON", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Export JSON", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Close settings", exact: true }).click();
    await page.keyboard.press("ControlOrMeta+k");
    await page.getByRole("searchbox", { name: "Search catalogue", exact: true }).fill(`${deviceId} temperature`);
    await page.getByRole("button", { name: "temperature, preview", exact: true }).click();
    const preview = page.getByRole("region", { name: "Reading preview", exact: true });
    await expect(preview).toBeVisible();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    const collection = preview.getByRole("region", { name: "Recording configuration", exact: true });
    expect((await readSystem()).runtime.bindings?.[stream.id]?.policy.mode).toBe("off");
    // Choosing a rate saves it at once; there is no separate apply step.
    await collection.getByLabel("Seconds between samples", { exact: true }).fill("1");
    expect((await readSystem()).runtime.collection_revision).toBe(initial.runtime.collection_revision);
    await collection.getByRole("radio", { name: /^At intervals/ }).check();
    await expect(collection.getByText("Every 1 s", { exact: true })).toBeVisible({ timeout: 120_000 });
    const applied = await readSystem();
    expect(keys.map(key => {
      const reading = applied.document.readings.find(item => item.topic === `tests/${localId}/${key}`)!;
      return applied.runtime.bindings?.[reading.id]?.policy.mode;
    })).toEqual(["sample", "off", "off"]);
    const binding = applied.runtime.bindings![stream.id]!;
    // How a reading is stored stays inside; the API names it by catalogue id.
    for (const field of ["entity_id", "telemetry_key", "accepted_topic"]) expect(binding).not.toHaveProperty(field);
    await expectNoHorizontalScroll(page);
    await expect(page.getByRole("button", { name: "View live", exact: true })).toHaveCount(0);
    await waitForCollectionReady(api, token!, applied, stream.broker_id);
    publisher = await connectAsync(process.env.MQTT_SOURCE_URL ?? "mqtt://127.0.0.1:1884", { clientId: `ui-${deviceId}` });
    for (const key of keys) await publisher.publishAsync(`tests/${localId}/${key}`, "25", { qos: 1 });
    const measured = async (readingId: string) => {
      const response = await api.get(`/api/v1/readings/${encodeURIComponent(readingId)}/measurements`, { headers });
      expect(response.ok(), await response.text()).toBe(true);
      return await response.json() as Array<{ value: number }>;
    };
    // Only the opted-in reading records; the others stay off.
    const unrecorded = keys.slice(1).map(key => applied.document.readings.find(item => item.topic === `tests/${localId}/${key}`)!.id);
    await expect.poll(async () => (await measured(stream.id)).length).toBeGreaterThan(0);
    for (const readingId of unrecorded) expect(await measured(readingId)).toEqual([]);
    for (const key of keys) await publisher.publishAsync(`tests/${localId}/${key}`, "26", { qos: 1 });
    await expect.poll(async () => {
      const response = await api.post("/api/v1/recording/status", { headers, data: { reading_ids: [stream.id] } });
      const status = await response.json();
      return status.runtime.latest_readings[stream.id]?.value;
    }).toEqual(26);
    await page.keyboard.press("ControlOrMeta+k");
    const receivingReading = page.getByRole("button", { name: "temperature, preview", exact: true });
    await expect(receivingReading.locator(".source-activity-dot")).toHaveClass(/is-receiving/, { timeout: 15_000 });
    await expect(receivingReading).toHaveAccessibleDescription("Receiving data (last 2 minutes)");
    await page.getByRole("button", { name: "Close navigation", exact: true }).click();
    await page.getByRole("button", { name: "Show sidebar", exact: true }).click();

    // Background collection continues after the page has been left.
    await page.goto("/anomalies");
    await publisher.publishAsync(`tests/${localId}/temperature`, "27", { qos: 1 });
    await expect.poll(async () => (await measured(stream.id)).some(point => point.value === 27)).toBe(true);
    await page.goto(`/?reading=${encodeURIComponent(stream.id)}`);
    await expect(preview.locator(".ex-preview-value strong")).toHaveText("27");
    await expect(preview.getByText("Reading preview", { exact: true })).toHaveCount(0);
    await expect(preview.getByRole("status").filter({ hasText: "Recording" })).toHaveText("Recording");
    await expect(preview.locator(".ex-preview-value time")).toHaveText(/^(just now|\d+ (seconds?|minutes?) ago)$/);
    await expect(preview.getByRole("navigation", { name: "Catalogue ancestry" })).toBeHidden();
    await preview.getByText("Source details", { exact: true }).click();
    await expect(preview.getByRole("navigation", { name: "Catalogue ancestry" })).toBeVisible();
    await preview.getByText("Source details", { exact: true }).click();
    await expect(preview.locator('.ex-preview-chart[role="img"]')).toBeVisible();
    await expectNoHorizontalScroll(page);
    await page.getByRole("button", { name: "Zoom in", exact: true }).click();
    await expect(page.getByRole("button", { name: "Reset zoom", exact: true })).toBeEnabled();
    await page.getByRole("button", { name: "Reset zoom", exact: true }).click();
    await expect(page.getByRole("button", { name: "Reset zoom", exact: true })).toBeDisabled();
    const allHistory = page.getByRole("group", { name: "Chart time range", exact: true }).getByRole("button", { name: "All", exact: true });
    await allHistory.click();
    await expect(allHistory).toHaveAttribute("aria-pressed", "true");
    await page.getByRole("button", { name: "Show sidebar", exact: true }).click();
    await workspaces.getByRole("link", { name: "Sources", exact: true }).click();
    await expect(collection.getByRole("radio", { name: /^At intervals/ })).toBeChecked();
    const stored = await api.get(`/api/v1/readings/${encodeURIComponent(stream.id)}/measurements/buckets`, { headers });
    expect(stored.ok(), await stored.text()).toBe(true);
    expect((await stored.json() as Array<{ value: number }>).some(point => point.value === 27)).toBe(true);
    for (const readingId of unrecorded) expect(await measured(readingId)).toEqual([]);

    await page.goto(`/?create=monitoring&reading=${encodeURIComponent(stream.id)}`);
    await expect(page.getByRole("region", { name: "Create monitoring service", exact: true })).toBeVisible();
    await page.getByRole("textbox", { name: "Service name", exact: true }).fill("Workspace monitor");
    await page.getByLabel("Warm-up samples", { exact: true }).fill("2");
    await page.getByLabel("Calibration samples", { exact: true }).fill("2");
    await page.getByRole("link", { name: "Review recording in Sources", exact: true }).click();
    await expect(page.getByRole("main", { name: "Sources workspace", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Show sidebar", exact: true }).click();
    await workspaces.getByRole("link", { name: "Monitoring", exact: true }).click();
    await expect(page.getByRole("textbox", { name: "Service name", exact: true })).toHaveValue("Workspace monitor");
    await expect(page.getByLabel("Warm-up samples", { exact: true })).toHaveValue("2");
    await expect(page.getByLabel("Calibration samples", { exact: true })).toHaveValue("2");
    const startedResponse = page.waitForResponse(response => new URL(response.url()).pathname.endsWith("/v1/monitors") && response.request().method() === "POST");
    await page.getByRole("button", { name: "Start adaptive monitoring", exact: true }).click();
    const started = await startedResponse;
    expect(started.ok(), await started.text()).toBeTruthy();
    serviceId = ((await started.json()) as { monitor_id: string }).monitor_id;
    // The form opens the service once its pipeline activation created the workload.
    await expect(page.getByRole("region", { name: "Monitoring service details", exact: true })).toBeVisible({ timeout: 240_000 });
    await page.getByRole("button", { name: "Rename service", exact: true }).click();
    const serviceName = page.getByRole("textbox", { name: "Rename service", exact: true });
    await serviceName.fill("Saved workspace monitor");
    await serviceName.press("Enter");
    await expect(page.getByRole("button", { name: "Rename service", exact: true })).toHaveText("Saved workspace monitor");
    // The star shows at once; reload only after the account has saved it.
    const favouriteSaved = page.waitForResponse(response => new URL(response.url()).pathname.endsWith("/v1/favorites")
      && response.request().method() === "POST");
    await page.getByRole("button", { name: "Add service to favourites", exact: true }).click();
    const favourite = await favouriteSaved;
    expect(favourite.ok(), await favourite.text()).toBeTruthy();
    await page.reload();
    await expect(page.getByRole("button", { name: "Remove service from favourites", exact: true })).toBeVisible();
    await page.setViewportSize({ width: 1440, height: 1000 });
    const catalogue = await page.getByRole("navigation", { name: "Catalogue", exact: true }).elementHandle();
    const source = new URL(page.url()).searchParams.get("source");
    for (const section of ["Sources", "Reporting", "Monitoring"]) {
      await workspaces.getByRole("link", { name: section, exact: true }).click();
      // The open service names its own page; the workspace becomes its breadcrumb.
      // A selected source likewise titles Sources.
      await expect(section === "Monitoring"
        ? page.getByRole("heading", { level: 1, name: "Saved workspace monitor", exact: true })
        : section === "Sources" ? page.getByRole("main", { name: "Sources workspace", exact: true })
          : page.getByRole("heading", { name: section, exact: true })).toBeVisible();
      expect(await catalogue!.evaluate(element => element.isConnected)).toBe(true);
      expect(new URL(page.url()).searchParams.get("source")).toBe(source);
    }
    await expect(page.getByRole("region", { name: "Monitoring service details", exact: true })).toBeVisible();
    await catalogue!.dispose();
    await expect.poll(async () => {
      const response = await api.get("/api/v1/monitors?active=true", { headers });
      const services = await response.json() as Array<{ id: string; display_name?: string; operational_status: { stage: string } }>;
      const service = services.find(item => item.id === serviceId);
      expect(service?.display_name).toBe("Saved workspace monitor");
      return service?.operational_status.stage;
    }, { timeout: 120_000, intervals: [1000] }).toBe("waiting_for_data");
    for (let index = 0; index < 7; index++) {
      await publisher.publishAsync(`tests/${localId}/temperature`, String(30 + index), { qos: 1 });
      await page.waitForTimeout(1100);
    }
    await expect.poll(async () => {
      const response = await api.get(`/api/v1/evidence?reading_id=${encodeURIComponent(stream.id)}`, { headers });
      const evidence = await response.json() as Array<{ monitor_id: string; anomaly_score: number | null; threshold: number | null }>;
      return evidence.some(row => row.monitor_id === serviceId && row.anomaly_score !== null && row.threshold !== null);
    }).toBe(true);
    await page.getByRole("tab", { name: "Evidence", exact: true }).click();
    const monitoringHistory = page.getByRole("region", { name: "Monitoring history", exact: true });
    await expect(monitoringHistory.getByRole("img", { name: /^1 displayed reading of 1 monitored input:/ })).toBeVisible();
    await expect(monitoringHistory.getByLabel("Latest detector result", { exact: true })).toContainText("Anomaly score:");
    await monitoringHistory.getByRole("button", { name: "Zoom in", exact: true }).click();
    await expect(monitoringHistory.getByRole("button", { name: "Return to live", exact: true })).toBeVisible();
    await monitoringHistory.getByRole("button", { name: "Return to live", exact: true }).click();
    await expect(monitoringHistory.getByRole("button", { name: "Live", exact: true })).toBeDisabled();
    await setAppearance(page, "Dark");
    await page.screenshot({ path: testInfo.outputPath("monitoring-shared-workspace.png") });
    await page.getByRole("button", { name: "Service actions", exact: true }).click();
    await page.getByRole("menuitem", { name: "Stop and remove service", exact: true }).click();
    await page.getByRole("dialog", { name: "Stop and remove service?", exact: true }).getByRole("button", { name: "Remove service", exact: true }).click();
    await expect(page.getByRole("heading", { name: "No monitoring services", exact: true })).toBeVisible();
    serviceId = undefined;
  } finally {
    await publisher?.endAsync();
    if (token && serviceId) await api.delete(`/api/v1/monitors/${encodeURIComponent(serviceId)}`, { headers: { Authorization: `Bearer ${token}` } });
    if (token) await removeTestCharger(api, token, deviceId);
    await api.dispose();
  }
});
