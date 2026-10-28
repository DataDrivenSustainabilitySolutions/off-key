import { randomUUID } from "node:crypto";
import { expect, test, type Page } from "@playwright/test";
import { connectAsync, type MqttClient } from "mqtt";
import type { SystemSnapshot } from "../src/types/system";
import { setAppearance } from "./helpers/appearance";
import { accessToken } from "./helpers/auth";
import { expectNoHorizontalScroll } from "./helpers/layout";

async function createFixture(page: Page, count = 40) {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Application menu", exact: true })).toBeVisible();
  const token = await accessToken(page);
  expect(token).toBeTruthy();
  const headers = { Authorization: `Bearer ${token}` };
  const read = async () => {
    const response = await page.request.get("/api/v1/system", { headers });
    expect(response.ok(), await response.text()).toBe(true);
    return await response.json() as SystemSnapshot;
  };
  // Search matches IDs too, so keep digits out of them: a hex ID containing "30"
  // would make every extra broker match the "Root navigation broker 30" search.
  const run = randomUUID().slice(0, 8).replace(/\d/g, digit => "ghijklmnop"[Number(digit)]!);
  const broker = "nav-broker-" + run;
  const north = "nav-north-" + run, south = "nav-south-" + run;
  const snapshot = await read();
  snapshot.document.connections.push({ id: broker, label: "Navigation broker " + run, protocol: "mqtt", host: "source-broker", port: 1883, transport: "tcp", tls: false });
  snapshot.document.devices.push(...[
    { id: north, label: "North room " + run, kind: "sensor", connection_id: broker },
    { id: south, label: "South room " + run, kind: "sensor", connection_id: broker },
  ]);
  const streams = Array.from({ length: count + 1 }, (_, position) => ({
    id: "nav-" + run + "-" + position, label: position === count ? "South value" : "North value " + String(position + 1).padStart(2, "0"),
    topic: "navigation/" + run + "/" + (position === count ? "south" : "north") + "/reading-" + String(position + 1).padStart(2, "0"),
    device_id: position === count ? south : north, connection_id: broker, value_type: "number" as const, category: "Navigation test",
  }));
  snapshot.document.streams.push(...streams);
  const response = await page.request.put("/api/v1/system", { headers, data: { expected_revision: snapshot.revision, document: snapshot.document } });
  expect(response.ok(), await response.text()).toBe(true);
  const ownedIds = new Set([broker, north, south, ...streams.map(stream => stream.id)]);
  return { broker, north, south, streams, headers, read, ownedIds,
    snapshot: await response.json() as SystemSnapshot,
    cleanup: async () => {
      const current = await read();
      current.document.groups = current.document.groups.filter(group => !ownedIds.has(group.id));
      current.document.streams = current.document.streams.filter(stream => !ownedIds.has(stream.id));
      current.document.devices = current.document.devices.filter(device => !ownedIds.has(device.id));
      current.document.connections = current.document.connections.filter(connection => !ownedIds.has(connection.id));
      const saved = await page.request.put("/api/v1/system", { headers, data: { expected_revision: current.revision, document: current.document } });
      expect(saved.ok(), await saved.text()).toBe(true);
    },
  };
}

test("returns to the catalogue root from collections, branches and search with a compact count", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  const fixture = await createFixture(page, 1);
  try {
    const snapshot = await fixture.read();
    const extraBrokers = Array.from({ length: 30 }, (_, index) => ({ ...snapshot.document.connections.find(item => item.id === fixture.broker)!,
      id: fixture.broker + "-extra-" + index, label: "Root navigation broker " + String(index + 1).padStart(2, "0") }));
    const collection = { id: fixture.broker + "-collection", label: "North site", member_ids: [fixture.broker, fixture.north, fixture.streams[0]!.id] };
    for (const id of [collection.id, ...extraBrokers.map(broker => broker.id)]) fixture.ownedIds.add(id);
    snapshot.document.connections.push(...extraBrokers);
    snapshot.document.groups.push(collection);
    const saved = await page.request.put("/api/v1/system", { headers: fixture.headers, data: { expected_revision: snapshot.revision, document: snapshot.document } });
    expect(saved.ok(), await saved.text()).toBe(true);
    await page.reload();
    const sidebar = page.getByRole("navigation", { name: "System explorer", exact: true });
    const root = sidebar.getByRole("button", { name: "Back to catalogue", exact: true });
    const collections = sidebar.getByRole("button", { name: "Browse collections", exact: true });
    const search = sidebar.getByRole("searchbox", { name: "Search catalogue", exact: true });
    const brokerCount = snapshot.document.connections.length + " brokers";
    await expect(sidebar.getByText(brokerCount, { exact: true })).toBeVisible();
    await expect(sidebar.getByRole("button", { name: snapshot.document.label, exact: true })).toHaveCount(0);
    await expect(root).toHaveAttribute("title", "Back to catalogue");
    await page.getByRole("button", { name: "Catalogue settings", exact: true }).click();
    await page.getByRole("button", { name: "Add collection", exact: true }).click();
    const collectionName = "Collection check " + fixture.broker.slice(-8);
    await page.getByRole("textbox", { name: "collection name", exact: true }).fill(collectionName);
    await expect(page.getByRole("textbox", { name: "Find collection members", exact: true })).toBeVisible();
    const collectionSaved = page.waitForResponse(response => response.request().method() === "PUT" && new URL(response.url()).pathname === "/api/v1/system");
    await page.getByRole("button", { name: "Save changes", exact: true }).click();
    const created = await collectionSaved;
    expect(created.ok(), await created.text()).toBe(true);
    const createdId = (await created.json() as SystemSnapshot).document.groups.find(group => group.label === collectionName)?.id;
    expect(createdId).toBeTruthy();
    fixture.ownedIds.add(createdId!);
    await expect(page.getByRole("dialog")).toHaveCount(0);
    const viewport = sidebar.getByRole("list", { name: "Catalogue items", exact: true }).locator("..");
    await viewport.evaluate(element => { element.scrollTop = 1400; });
    expect(await viewport.evaluate(element => element.scrollTop)).toBeGreaterThan(0);
    await root.click();
    await expect.poll(() => viewport.evaluate(element => element.scrollTop)).toBe(0);
    await collections.click();
    const choose = page.getByRole("button", { name: "Show collection North site", exact: true });
    await expect(choose.locator("small")).toHaveText("3");
    await choose.click();
    await expect(sidebar.getByText("3 items", { exact: true })).toBeVisible();
    await sidebar.getByRole("button", { name: "North room " + fixture.north.slice(-8) + ", open", exact: true }).click();
    expect(new URL(page.url()).searchParams.get("source")).toBeTruthy();
    await root.click();
    await expect(sidebar.getByText(brokerCount, { exact: true })).toBeVisible();
    expect(new URL(page.url()).searchParams.has("source")).toBe(false);
    await sidebar.getByRole("button", { name: "Browse children of Navigation broker " + fixture.broker.slice(-8), exact: true }).click();
    await expect(sidebar.getByRole("button", { name: "Back one level", exact: true })).toBeVisible();
    await root.click();
    await expect(sidebar.getByRole("button", { name: "Back one level", exact: true })).toHaveCount(0);
    await search.fill("Root navigation broker 30");
    await expect(sidebar.getByText("1 match", { exact: true })).toBeVisible();
    await root.click();
    await expect(search).toHaveValue("");
    await expect(sidebar.getByText(brokerCount, { exact: true })).toBeVisible();
    for (const appearance of ["Light", "Dark"] as const) {
      await setAppearance(page, appearance);
      await sidebar.screenshot({ path: testInfo.outputPath("catalogue-root-" + appearance.toLowerCase() + ".png"), animations: "disabled" });
    }
    await page.setViewportSize({ width: 320, height: 844 });
    await page.getByRole("button", { name: "Show catalogue", exact: true }).click();
    await expect(root).toBeInViewport();
    const buttonBox = await root.boundingBox();
    expect(buttonBox!.width).toBeGreaterThanOrEqual(44);
    expect(buttonBox!.height).toBeGreaterThanOrEqual(44);
    await collections.click();
    await page.getByRole("button", { name: "Show collection North site", exact: true }).click();
    await root.focus();
    await root.press("Enter");
    await expect(sidebar.getByText(brokerCount, { exact: true })).toBeVisible();
    await expectNoHorizontalScroll(page);
    await page.screenshot({ path: testInfo.outputPath("catalogue-root-mobile.png"), animations: "disabled" });
  } finally { await fixture.cleanup(); }
});

test("keeps the catalogue DOM, selection, search and scroll while navigating and protects recording drafts", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const fixture = await createFixture(page);
  let publisher: MqttClient | undefined;
  let leaseId: string | undefined;
  let disconnected = false;
  try {
    let catalogueReads = 0;
    let previewStarts = 0, previewStops = 0;
    page.on("request", request => {
      if (request.method() === "GET" && new URL(request.url()).pathname === "/api/v1/system") catalogueReads++;
      const path = new URL(request.url()).pathname;
      if (request.method() === "POST" && path === "/api/v1/system/live/leases") previewStarts++;
      if (request.method() === "DELETE" && path.startsWith("/api/v1/system/live/leases/")) previewStops++;
    });
    await page.reload();
    const sidebar = page.getByRole("navigation", { name: "System explorer", exact: true });
    const navigation = page.getByRole("navigation", { name: "Primary navigation", exact: true });
    await sidebar.getByRole("button", { name: "Browse children of Navigation broker " + fixture.broker.slice(-8), exact: true }).click();
    await sidebar.getByRole("button", { name: "Browse children of North room " + fixture.north.slice(-8), exact: true }).click();
    await sidebar.getByRole("button", { name: /^Browse children of navigation\// }).click();
    const search = sidebar.getByRole("searchbox", { name: "Search catalogue", exact: true });
    await search.fill("North value");
    const list = sidebar.getByRole("list", { name: "Catalogue items", exact: true });
    const viewport = list.locator("..");
    await viewport.evaluate(element => { element.scrollTop = 29 * 72; });
    const selected = sidebar.getByRole("button", { name: "North value 30, preview", exact: true });
    await selected.click();
    await expect(page.getByRole("region", { name: "Reading preview", exact: true })).toBeVisible();
    const connected = page.waitForResponse(response => response.request().method() === "POST"
      && new URL(response.url()).pathname === "/api/v1/system/live/leases");
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    const lease = await connected;
    expect(lease.ok(), await lease.text()).toBe(true);
    leaseId = (await lease.json() as { lease_id: string }).lease_id;
    await expect(page.locator(".sp-live-indicator")).toHaveText("Live");
    publisher = await connectAsync(process.env.MQTT_SOURCE_URL ?? "mqtt://127.0.0.1:1884");
    await publisher.publishAsync(fixture.streams[29]!.topic, "42", { qos: 1 });
    await expect(page.locator(".ex-preview-value strong")).toHaveText("42");
    const source = new URL(page.url()).searchParams.get("source");
    const resize = page.getByRole("separator", { name: "Resize explorer sidebar", exact: true });
    const initialWidth = Number(await resize.getAttribute("aria-valuenow"));
    await resize.press("ArrowRight");
    await expect(resize).toHaveAttribute("aria-valuenow", String(initialWidth + 16));
    const sidebarHandle = await sidebar.elementHandle(), listHandle = await list.elementHandle();
    const readsBeforeNavigation = catalogueReads;
    const offset = await viewport.evaluate(element => element.scrollTop);
    expect(offset).toBeGreaterThan(100);
    const unchanged = async () => {
      expect(await sidebarHandle!.evaluate(element => element.isConnected)).toBe(true);
      expect(await listHandle!.evaluate(element => element.isConnected)).toBe(true);
      await expect(search).toHaveValue("North value");
      await expect(selected).toHaveAttribute("aria-current", "true");
      expect(await viewport.evaluate(element => element.scrollTop)).toBeCloseTo(offset, 0);
      expect(new URL(page.url()).searchParams.get("source")).toBe(source);
      await expect(resize).toHaveAttribute("aria-valuenow", String(initialWidth + 16));
      expect(catalogueReads).toBe(readsBeforeNavigation);
      expect(previewStarts).toBe(1);
      expect(previewStops).toBe(0);
    };
    await navigation.getByRole("link", { name: "Sources", exact: true }).click();
    await expect(page.getByLabel("Recording policy", { exact: true })).toBeVisible();
    await unchanged();
    await page.getByLabel("Recording policy", { exact: true }).selectOption("sample");
    await navigation.getByRole("link", { name: "Reporting", exact: true }).click();
    const guard = page.getByRole("dialog", { name: "Unsaved recording changes", exact: true });
    await guard.getByRole("button", { name: "Stay", exact: true }).click();
    await expect(page.getByLabel("Recording policy", { exact: true })).toHaveValue("sample");
    await unchanged();
    await navigation.getByRole("link", { name: "Reporting", exact: true }).click();
    await guard.getByRole("button", { name: "Discard and leave", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Reporting", exact: true })).toBeVisible();
    await unchanged();
    await page.goBack();
    await expect(page.getByLabel("Recording policy", { exact: true })).toHaveValue("inherit");
    await unchanged();
    await navigation.getByRole("link", { name: "Monitoring", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Monitoring", exact: true })).toBeVisible();
    await unchanged();
    await page.getByRole("button", { name: "Hide catalogue", exact: true }).click();
    await expect(navigation.getByRole("link", { name: "Sources", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Show catalogue", exact: true }).click();
    for (const appearance of ["Light", "Dark"] as const) {
      await setAppearance(page, appearance);
      await page.screenshot({ path: testInfo.outputPath("workspace-" + appearance.toLowerCase() + ".png") });
    }

    await page.setViewportSize({ width: 320, height: 844 });
    for (const section of ["Sources", "Reporting", "Monitoring"]) {
      await expect(navigation.getByRole("link", { name: section, exact: true })).toBeInViewport();
      await navigation.getByRole("link", { name: section, exact: true }).click();
      // With a source selected, Sources is titled by that source.
      await expect(section === "Sources" ? page.getByRole("main", { name: "Sources workspace", exact: true })
        : page.getByRole("heading", { name: section, exact: true })).toBeVisible();
      expect(new URL(page.url()).searchParams.get("source")).toBe(source);
      await expectNoHorizontalScroll(page);
    }
    await page.getByRole("button", { name: "Show catalogue", exact: true }).click();
    await expect(search).toHaveValue("North value");
    await expect(selected).toHaveAttribute("aria-current", "true");
    await page.getByRole("button", { name: "Hide catalogue", exact: true }).click();
    await expect(page.getByRole("button", { name: "Show catalogue", exact: true })).toBeFocused();
    await page.screenshot({ path: testInfo.outputPath("workspace-mobile.png") });
    expect(catalogueReads).toBe(readsBeforeNavigation);
    await expect(page.locator(".ex-preview-value strong")).toHaveText("42");
    expect(previewStarts).toBe(1); expect(previewStops).toBe(0);
    await page.getByRole("button", { name: "Disconnect", exact: true }).click();
    await expect.poll(() => previewStops).toBe(1);
    disconnected = true;
    await sidebarHandle!.dispose(); await listHandle!.dispose();
  } finally {
    await publisher?.endAsync();
    if (leaseId && !disconnected) await page.request.delete("/api/v1/system/live/leases/" + leaseId, { headers: fixture.headers });
    await fixture.cleanup();
  }
});

test("filters online topics and their paths as real MQTT traffic starts and expires", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const fixture = await createFixture(page, 2);
  const run = fixture.broker.slice(-8);
  let publisher: MqttClient | undefined;
  let publishTimer: ReturnType<typeof setInterval> | undefined;
  try {
    const current = await fixture.read();
    const collection = { id: fixture.broker + "-online", label: "Online check " + run, member_ids: fixture.streams.map(stream => stream.id) };
    fixture.ownedIds.add(collection.id);
    current.document.groups.push(collection);
    const saved = await page.request.put("/api/v1/system", { headers: fixture.headers,
      data: { expected_revision: current.revision, document: current.document } });
    expect(saved.ok(), await saved.text()).toBe(true);
    const configured = await saved.json() as SystemSnapshot;
    const applied = await page.request.put("/api/v1/system/collection", { headers: fixture.headers, data: {
      expected_revision: configured.revision, expected_collection_revision: configured.runtime.collection_revision,
      stream_ids: fixture.streams.slice(0, 2).map(stream => stream.id), policy: { mode: "sample", interval_seconds: 3600 },
    } });
    expect(applied.ok(), await applied.text()).toBe(true);
    await expect.poll(async () => (await fixture.read()).runtime.ingress?.sources?.[fixture.broker]?.state,
      { timeout: 120_000 }).toBe("connected");
    publisher = await connectAsync(process.env.MQTT_SOURCE_URL ?? "mqtt://127.0.0.1:1884");
    const publish = () => publisher!.publish(fixture.streams[0]!.topic, "23", { qos: 1 });
    publish(); publishTimer = setInterval(publish, 500);
    let previewStarts = 0, configurationWrites = 0;
    page.on("request", request => {
      const path = new URL(request.url()).pathname;
      if (request.method() === "POST" && path === "/api/v1/system/live/leases") previewStarts++;
      if (request.method() === "PUT" && path.startsWith("/api/v1/system")) configurationWrites++;
    });
    await page.reload();
    const sidebar = page.getByRole("navigation", { name: "System explorer", exact: true });
    const search = sidebar.getByRole("searchbox", { name: "Search catalogue", exact: true });
    const toggle = sidebar.getByRole("button", { name: "Online topics only", exact: true });
    const root = sidebar.getByRole("button", { name: "Back to catalogue", exact: true });
    const active = sidebar.getByRole("button", { name: "North value 01, preview", exact: true });
    const quiet = sidebar.getByRole("button", { name: "North value 02, preview", exact: true });
    await search.fill(run);
    await expect(active.locator("svg")).toHaveAttribute("fill", "currentColor");
    await quiet.click();
    const selection = page.url();
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-pressed", "true");
    await expect(quiet).toHaveCount(0);
    await expect(sidebar.getByRole("button", { name: "South room " + run + ", open", exact: true })).toHaveCount(0);
    await expect(page).toHaveURL(selection);
    await expect(search).toHaveValue(run);
    await root.click();
    await expect(toggle).toHaveAttribute("aria-pressed", "true");
    await sidebar.getByRole("button", { name: "Browse children of Navigation broker " + run, exact: true }).click();
    await expect(sidebar.getByRole("button", { name: "North room " + run + ", open", exact: true })).toBeVisible();
    await expect(sidebar.getByRole("button", { name: "South room " + run + ", open", exact: true })).toHaveCount(0);
    await sidebar.getByRole("button", { name: "Browse children of North room " + run, exact: true }).click();
    await expect(sidebar.getByRole("button", { name: "navigation/" + run + "/north/reading-01, preview", exact: true })).toBeVisible();
    await page.getByRole("navigation", { name: "Primary navigation", exact: true }).getByRole("link", { name: "Sources", exact: true }).click();
    await expect(toggle).toHaveAttribute("aria-pressed", "true");
    await expect.poll(() => page.evaluate(() => {
      const entry = Object.entries(localStorage).find(([key]) => key.startsWith("aberration:explorer:v1:"));
      return entry ? (JSON.parse(entry[1]) as { onlineOnly?: boolean }).onlineOnly : false;
    })).toBe(true);
    await page.reload();
    await expect(toggle).toHaveAttribute("aria-pressed", "true");
    await sidebar.getByRole("button", { name: "Browse collections", exact: true }).click();
    await page.getByRole("button", { name: "Show collection " + collection.label, exact: true }).click();
    await expect(sidebar.getByText("1 item", { exact: true })).toBeVisible();
    await expect(active).toBeVisible();
    for (const appearance of ["Light", "Dark"] as const) {
      await setAppearance(page, appearance);
      await sidebar.screenshot({ path: testInfo.outputPath("online-topics-" + appearance.toLowerCase() + ".png"), animations: "disabled" });
    }
    await toggle.click();
    await expect(sidebar.getByText("3 items", { exact: true })).toBeVisible();
    await expect(quiet).toBeVisible();
    await toggle.click();
    clearInterval(publishTimer); publishTimer = undefined;
    await expect(sidebar.getByText("No active topics", { exact: true })).toBeVisible({ timeout: 40_000 });
    const showAll = sidebar.getByRole("button", { name: "Show all topics", exact: true });
    await expect(showAll).toHaveCSS("text-decoration-line", "underline");
    await sidebar.locator(".ex-list-empty").screenshot({ path: testInfo.outputPath("no-active-topics.png") });
    await showAll.focus(); await showAll.press("Enter");
    await expect(toggle).toHaveAttribute("aria-pressed", "false");
    await expect(sidebar.getByText("3 items", { exact: true })).toBeVisible();
    await toggle.click();
    await expect(sidebar.getByText("No active topics", { exact: true })).toBeVisible();
    await publisher.publishAsync(fixture.streams[0]!.topic, "24", { qos: 1 });
    await expect(active.locator("svg")).toHaveAttribute("fill", "currentColor");
    await page.setViewportSize({ width: 320, height: 844 });
    await page.getByRole("button", { name: "Show catalogue", exact: true }).click();
    await expect(toggle).toHaveAttribute("aria-pressed", "true");
    await expect(toggle).toBeInViewport();
    const box = await toggle.boundingBox();
    expect(box!.width).toBeGreaterThanOrEqual(44); expect(box!.height).toBeGreaterThanOrEqual(44);
    await expect(root).toBeInViewport();
    await expectNoHorizontalScroll(page);
    await page.screenshot({ path: testInfo.outputPath("online-topics-mobile.png"), animations: "disabled" });
    expect(previewStarts).toBe(0); expect(configurationWrites).toBe(0);
  } finally {
    clearInterval(publishTimer);
    await publisher?.endAsync();
    await fixture.cleanup();
  }
});

test("filters real recorded reports by entity and reading across the shared navbar", async ({ page }) => {
  const fixture = await createFixture(page, 2);
  const anomalies: string[] = [];
  let publisher: MqttClient | undefined;
  try {
    const applied = await page.request.put("/api/v1/system/collection", { headers: fixture.headers, data: {
      expected_revision: fixture.snapshot.revision, expected_collection_revision: fixture.snapshot.runtime.collection_revision,
      stream_ids: fixture.streams.map(stream => stream.id), policy: { mode: "original", interval_seconds: 10 },
    } });
    expect(applied.ok(), await applied.text()).toBe(true);
    const snapshot = await applied.json() as SystemSnapshot;
    await expect.poll(async () => {
      const current = await fixture.read();
      return current.runtime.collection?.status === "applied" && current.runtime.collection.revision === snapshot.runtime.collection_revision
        && current.runtime.ingress?.revision === snapshot.runtime.collection_revision && current.runtime.ingress?.sources?.[fixture.broker]?.state === "connected";
    }, { timeout: 120_000 }).toBe(true);
    publisher = await connectAsync(process.env.MQTT_SOURCE_URL ?? "mqtt://127.0.0.1:1884");
    for (const stream of fixture.streams) await publisher.publishAsync(stream.topic, "23", { qos: 1 });
    const north = snapshot.runtime.bindings![fixture.streams[0]!.id]!;
    await expect.poll(async () => {
      const response = await page.request.get("/api/v1/telemetry/" + north.entity_id + "/type", { headers: fixture.headers });
      return response.ok() ? response.json() : [];
    }).toContain(north.telemetry_key);
    const names = ["North first " + fixture.north, "North second " + fixture.north, "South report " + fixture.south];
    for (const [position, stream] of fixture.streams.entries()) {
      const binding = snapshot.runtime.bindings![stream.id]!;
      await expect.poll(async () => {
        const response = await page.request.get("/api/v1/telemetry/" + binding.entity_id + "/type", { headers: fixture.headers });
        return response.ok() ? response.json() : [];
      }).toContain(binding.telemetry_key);
      const response = await page.request.post("/api/v1/anomalies", { headers: fixture.headers, data: { payload: {
        charger_id: binding.entity_id, timestamp: new Date().toISOString(), telemetry_type: binding.telemetry_key,
        anomaly_type: names[position], anomaly_value: .01, value_type: "tail_pvalue", sensor_set: [binding.telemetry_key],
      } } });
      expect(response.ok(), await response.text()).toBe(true);
      anomalies.push((await response.json() as { anomaly_id: string }).anomaly_id);
    }
    await page.goto("/anomalies");
    const navigation = page.getByRole("navigation", { name: "Primary navigation", exact: true });
    const search = page.getByRole("searchbox", { name: "Search catalogue", exact: true });
    await search.fill(fixture.north);
    await page.getByRole("button", { name: "North room " + fixture.north.slice(-8) + ", open", exact: true }).click();
    await expect(page.getByRole("cell", { name: names[0], exact: true })).toBeVisible();
    await expect(page.getByRole("cell", { name: names[1], exact: true })).toBeVisible();
    await expect(page.getByRole("cell", { name: names[2], exact: true })).toHaveCount(0);
    await navigation.getByRole("link", { name: "Sources", exact: true }).click();
    const entityReadings = page.getByRole("region", { name: "Entity readings", exact: true });
    await expect(entityReadings).toBeVisible();
    await expect(page.getByLabel("Recording policy", { exact: true })).toHaveCount(0);
    await entityReadings.getByRole("button", { name: /North value 01/ }).click();
    await expect(page.getByLabel("Recording policy", { exact: true })).toHaveValue("original");
    await navigation.getByRole("link", { name: "Reporting", exact: true }).click();
    await expect(page.getByRole("cell", { name: names[0], exact: true })).toBeVisible();
    await expect(page.getByRole("cell", { name: names[1], exact: true })).toHaveCount(0);
    await expect(page.getByRole("cell", { name: names[2], exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Show all sources", exact: true }).click();
    for (const name of names) await expect(page.getByRole("cell", { name, exact: true })).toBeVisible();
  } finally {
    await publisher?.endAsync();
    for (const id of anomalies) {
      const response = await page.request.delete("/api/v1/anomalies/" + id, { headers: fixture.headers });
      expect(response.ok(), await response.text()).toBe(true);
    }
    await fixture.cleanup();
  }
});
