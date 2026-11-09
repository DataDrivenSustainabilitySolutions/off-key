import { randomUUID } from "node:crypto";
import { expect, test, type Page } from "@playwright/test";
import { connectAsync, type MqttClient } from "mqtt";
import type { SystemSnapshot } from "../src/types/system";
import { openCatalogueSettings, setAppearance } from "./helpers/appearance";
import { accessToken } from "./helpers/auth";
import { expectNoHorizontalScroll } from "./helpers/layout";

async function createFixture(page: Page, count = 40) {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Account menu", exact: true })).toBeVisible();
  const token = await accessToken(page);
  expect(token).toBeTruthy();
  const headers = { Authorization: `Bearer ${token}` };
  const read = async () => {
    const response = await page.request.get("/api/v1/catalogue", { headers });
    expect(response.ok(), await response.text()).toBe(true);
    return await response.json() as SystemSnapshot;
  };
  // Search matches IDs too, so keep digits out of them: a hex ID containing "30"
  // would make every extra broker match the "Root navigation broker 30" search.
  const run = randomUUID().slice(0, 8).replace(/\d/g, digit => "ghijklmnop"[Number(digit)]!);
  const broker = "nav-broker-" + run;
  const north = "nav-north-" + run, south = "nav-south-" + run;
  const snapshot = await read();
  snapshot.document.brokers.push({ id: broker, label: "Navigation broker " + run, protocol: "mqtt", host: "source-broker", port: 1883, transport: "tcp", tls: false });
  snapshot.document.devices.push(...[
    { id: north, label: "North room " + run, kind: "sensor", broker_id: broker },
    { id: south, label: "South room " + run, kind: "sensor", broker_id: broker },
  ]);
  const streams = Array.from({ length: count + 1 }, (_, position) => ({
    id: "nav-" + run + "-" + position, label: position === count ? "South value" : "North value " + String(position + 1).padStart(2, "0"),
    topic: "navigation/" + run + "/" + (position === count ? "south" : "north") + "/reading-" + String(position + 1).padStart(2, "0"),
    device_id: position === count ? south : north, broker_id: broker, value_type: "number" as const, category: "Navigation test",
  }));
  snapshot.document.readings.push(...streams);
  const response = await page.request.put("/api/v1/catalogue", { headers, data: { expected_revision: snapshot.revision, document: snapshot.document } });
  expect(response.ok(), await response.text()).toBe(true);
  const ownedIds = new Set([broker, north, south, ...streams.map(stream => stream.id)]);
  return { broker, north, south, streams, headers, read, ownedIds,
    snapshot: await response.json() as SystemSnapshot,
    cleanup: async () => {
      const current = await read();
      current.document.groups = current.document.groups.filter(group => !ownedIds.has(group.id));
      current.document.readings = current.document.readings.filter(stream => !ownedIds.has(stream.id));
      current.document.devices = current.document.devices.filter(device => !ownedIds.has(device.id));
      current.document.brokers = current.document.brokers.filter(connection => !ownedIds.has(connection.id));
      const saved = await page.request.put("/api/v1/catalogue", { headers, data: { expected_revision: current.revision, document: current.document } });
      expect(saved.ok(), await saved.text()).toBe(true);
    },
  };
}

test("narrows the tree to a collection, collapses every branch and restores the tree after a search", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  const fixture = await createFixture(page, 1);
  try {
    const snapshot = await fixture.read();
    const extraBrokers = Array.from({ length: 30 }, (_, index) => ({ ...snapshot.document.brokers.find(item => item.id === fixture.broker)!,
      id: fixture.broker + "-extra-" + index, label: "Root navigation broker " + String(index + 1).padStart(2, "0") }));
    const collection = { id: fixture.broker + "-collection", label: "North site", member_ids: [fixture.broker, fixture.north, fixture.streams[0]!.id] };
    for (const id of [collection.id, ...extraBrokers.map(broker => broker.id)]) fixture.ownedIds.add(id);
    snapshot.document.brokers.push(...extraBrokers);
    snapshot.document.groups.push(collection);
    const saved = await page.request.put("/api/v1/catalogue", { headers: fixture.headers, data: { expected_revision: snapshot.revision, document: snapshot.document } });
    expect(saved.ok(), await saved.text()).toBe(true);
    await page.reload();
    const sidebar = page.getByRole("complementary", { name: "Sidebar", exact: true });
    const tree = sidebar.getByRole("navigation", { name: "Catalogue", exact: true });
    const collapseAll = tree.getByRole("button", { name: "Collapse all", exact: true });
    const search = tree.getByRole("searchbox", { name: "Search catalogue", exact: true });
    const run = fixture.broker.slice(-8);
    const brokerRow = tree.getByRole("button", { name: "Navigation broker " + run + ", open", exact: true });
    const northRow = tree.getByRole("button", { name: "North room " + run + ", open", exact: true });
    // The extra brokers have no children, so their row action is preview.
    const emptyBroker = tree.getByRole("button", { name: "Root navigation broker 01, preview", exact: true });
    await expect(emptyBroker).toBeVisible();
    await openCatalogueSettings(page);
    await page.getByRole("button", { name: "Add collection", exact: true }).click();
    const collectionName = "Collection check " + run;
    await page.getByRole("textbox", { name: "collection name", exact: true }).fill(collectionName);
    await expect(page.getByRole("textbox", { name: "Find collection members", exact: true })).toBeVisible();
    const collectionSaved = page.waitForResponse(response => response.request().method() === "PUT" && new URL(response.url()).pathname === "/api/v1/catalogue");
    await page.getByRole("button", { name: "Save changes", exact: true }).click();
    const created = await collectionSaved;
    expect(created.ok(), await created.text()).toBe(true);
    const createdId = (await created.json() as SystemSnapshot).document.groups.find(group => group.label === collectionName)?.id;
    expect(createdId).toBeTruthy();
    fixture.ownedIds.add(createdId!);
    await expect(page.getByRole("dialog", { name: "Edit catalogue", exact: true })).toHaveCount(0);
    await page.getByRole("dialog", { name: "Settings", exact: true }).getByRole("button", { name: "Close settings", exact: true }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);

    // A collection narrows the tree to its members without choosing a source.
    const collections = sidebar.getByRole("region", { name: "Collections", exact: true });
    const choose = collections.getByRole("button", { name: "Show collection North site", exact: true });
    await expect(choose.locator("small")).toHaveText("3");
    const before = page.url();
    await choose.click();
    await expect(choose).toHaveAttribute("aria-pressed", "true");
    await expect(tree.getByText("In North site", { exact: true })).toBeVisible();
    await expect(emptyBroker).toHaveCount(0);
    expect(page.url()).toBe(before);
    await northRow.first().click();
    const source = new URL(page.url()).searchParams.get("source");
    expect(source).toBeTruthy();
    await tree.getByRole("button", { name: "Show every source", exact: true }).click();
    await expect(choose).toHaveAttribute("aria-pressed", "false");
    expect(new URL(page.url()).searchParams.get("source")).toBe(source);
    // The chosen room stays revealed, inside its open broker.
    await expect(brokerRow).toHaveAttribute("aria-expanded", "true");
    await expect(northRow).toHaveAttribute("aria-current", "true");

    // Collapsing every branch and searching change only what the tree shows.
    await collapseAll.click();
    await expect(northRow).toHaveCount(0);
    await expect(brokerRow).toHaveAttribute("aria-expanded", "false");
    await search.fill("Root navigation broker 30");
    await expect(tree.getByText("1 match", { exact: true })).toBeVisible();
    await search.press("Escape");
    await expect(search).toHaveValue("");
    await expect(brokerRow).toHaveAttribute("aria-expanded", "false");
    expect(new URL(page.url()).searchParams.get("source")).toBe(source);
    for (const appearance of ["Light", "Dark"] as const) {
      await setAppearance(page, appearance);
      await sidebar.screenshot({ path: testInfo.outputPath("catalogue-tree-" + appearance.toLowerCase() + ".png"), animations: "disabled" });
    }
    await page.setViewportSize({ width: 320, height: 844 });
    await page.getByRole("button", { name: "Show sidebar", exact: true }).click();
    const drawer = page.getByRole("dialog", { name: "Navigation", exact: true });
    const drawerCollapse = drawer.getByRole("button", { name: "Collapse all", exact: true });
    await drawerCollapse.scrollIntoViewIfNeeded();
    const buttonBox = await drawerCollapse.boundingBox();
    expect(buttonBox!.width).toBeGreaterThanOrEqual(44);
    expect(buttonBox!.height).toBeGreaterThanOrEqual(44);
    await drawer.getByRole("button", { name: "Show collection North site", exact: true }).click();
    await expect(drawer.getByText("In North site", { exact: true })).toBeVisible();
    await expectNoHorizontalScroll(page);
    await page.screenshot({ path: testInfo.outputPath("catalogue-tree-mobile.png"), animations: "disabled" });
    await drawer.getByRole("button", { name: "Show every source", exact: true }).click();
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
      if (request.method() === "GET" && new URL(request.url()).pathname === "/api/v1/catalogue") catalogueReads++;
      const path = new URL(request.url()).pathname;
      if (request.method() === "POST" && path === "/api/v1/live/views") previewStarts++;
      if (request.method() === "DELETE" && path.startsWith("/api/v1/live/views/")) previewStops++;
    });
    await page.reload();
    const sidebar = page.getByRole("navigation", { name: "Catalogue", exact: true });
    const navigation = page.getByRole("navigation", { name: "Workspace", exact: true });
    await sidebar.getByRole("button", { name: "Expand Navigation broker " + fixture.broker.slice(-8), exact: true }).click();
    await sidebar.getByRole("button", { name: "Expand North room " + fixture.north.slice(-8), exact: true }).click();
    await sidebar.getByRole("button", { name: /^Expand navigation\// }).click();
    const search = sidebar.getByRole("searchbox", { name: "Search catalogue", exact: true });
    await search.fill("North value");
    const list = sidebar.getByRole("list", { name: "Search results", exact: true });
    const viewport = list.locator("..");
    await viewport.evaluate(element => { element.scrollTop = 29 * 48; });
    const selected = sidebar.getByRole("button", { name: "North value 30, preview", exact: true });
    await selected.click();
    await expect(page.getByRole("region", { name: "Reading preview", exact: true })).toBeVisible();
    const connected = page.waitForResponse(response => response.request().method() === "POST"
      && new URL(response.url()).pathname === "/api/v1/live/views");
    await page.getByRole("button", { name: "View live", exact: true }).click();
    const lease = await connected;
    expect(lease.ok(), await lease.text()).toBe(true);
    leaseId = (await lease.json() as { view_id: string }).view_id;
    await expect(page.locator(".sp-live-indicator")).toHaveText("Live");
    publisher = await connectAsync(process.env.MQTT_SOURCE_URL ?? "mqtt://127.0.0.1:1884");
    await publisher.publishAsync(fixture.streams[29]!.topic, "42", { qos: 1 });
    await expect(page.locator(".ex-preview-value strong")).toHaveText("42");
    const source = new URL(page.url()).searchParams.get("source");
    const resize = page.getByRole("separator", { name: "Resize sidebar", exact: true });
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
    const recording = page.getByRole("radiogroup", { name: "Recording", exact: true });
    await expect(recording).toBeVisible();
    await unchanged();
    // Recording choices save when clicked, so leaving never asks about a draft.
    await navigation.getByRole("link", { name: "Reporting", exact: true }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Reporting", exact: true })).toBeVisible();
    await unchanged();
    await page.goBack();
    await expect(recording.getByRole("radio", { name: "Same as above", exact: true })).toBeChecked();
    await unchanged();
    await navigation.getByRole("link", { name: "Monitoring", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Monitoring", exact: true })).toBeVisible();
    await unchanged();
    await page.getByRole("button", { name: "Hide sidebar", exact: true }).click();
    await expect(page.getByRole("button", { name: "Show sidebar", exact: true })).toBeFocused();
    await page.getByRole("button", { name: "Show sidebar", exact: true }).click();
    await unchanged();
    for (const appearance of ["Light", "Dark"] as const) {
      await setAppearance(page, appearance);
      await page.screenshot({ path: testInfo.outputPath("workspace-" + appearance.toLowerCase() + ".png") });
    }

    await page.setViewportSize({ width: 320, height: 844 });
    // On phones the same navigation opens as a drawer that closes once a workspace is chosen.
    for (const section of ["Sources", "Reporting", "Monitoring"]) {
      await page.getByRole("button", { name: "Show sidebar", exact: true }).click();
      await expect(navigation.getByRole("link", { name: section, exact: true })).toBeInViewport();
      await navigation.getByRole("link", { name: section, exact: true }).click();
      await expect(page.getByRole("dialog", { name: "Navigation", exact: true })).toHaveCount(0);
      // With a source selected, Sources is titled by that source.
      await expect(section === "Sources" ? page.getByRole("main", { name: "Sources workspace", exact: true })
        : page.getByRole("heading", { name: section, exact: true })).toBeVisible();
      expect(new URL(page.url()).searchParams.get("source")).toBe(source);
      await expectNoHorizontalScroll(page);
    }
    await page.getByRole("button", { name: "Show sidebar", exact: true }).click();
    await expect(search).toHaveValue("North value");
    await expect(selected).toHaveAttribute("aria-current", "true");
    await page.getByRole("button", { name: "Close navigation", exact: true }).click();
    await expect(page.getByRole("button", { name: "Show sidebar", exact: true })).toBeFocused();
    await page.screenshot({ path: testInfo.outputPath("workspace-mobile.png") });
    expect(catalogueReads).toBe(readsBeforeNavigation);
    await expect(page.locator(".ex-preview-value strong")).toHaveText("42");
    expect(previewStarts).toBe(1); expect(previewStops).toBe(0);
    await page.getByRole("button", { name: "Stop live view", exact: true }).click();
    await expect.poll(() => previewStops).toBe(1);
    disconnected = true;
    await sidebarHandle!.dispose(); await listHandle!.dispose();
  } finally {
    await publisher?.endAsync();
    if (leaseId && !disconnected) await page.request.delete("/api/v1/live/views/" + leaseId, { headers: fixture.headers });
    await fixture.cleanup();
  }
});

test("filters online topics and their paths as real MQTT traffic starts and expires", async ({ page }, testInfo) => {
  // A fast reading keeps receiving for the 2 minute activity floor after it stops.
  test.setTimeout(300_000);
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
    const saved = await page.request.put("/api/v1/catalogue", { headers: fixture.headers,
      data: { expected_revision: current.revision, document: current.document } });
    expect(saved.ok(), await saved.text()).toBe(true);
    const configured = await saved.json() as SystemSnapshot;
    const applied = await page.request.put("/api/v1/recording", { headers: fixture.headers, data: {
      expected_revision: configured.revision, expected_collection_revision: configured.runtime.collection_revision,
      reading_ids: fixture.streams.slice(0, 2).map(stream => stream.id), policy: { mode: "sample", interval_seconds: 3600 },
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
      if (request.method() === "POST" && path === "/api/v1/live/views") previewStarts++;
      if (request.method() === "PUT" && (path === "/api/v1/catalogue" || path.startsWith("/api/v1/recording"))) configurationWrites++;
    });
    await page.reload();
    const sidebar = page.getByRole("navigation", { name: "Catalogue", exact: true });
    const search = sidebar.getByRole("searchbox", { name: "Search catalogue", exact: true });
    const toggle = sidebar.getByRole("button", { name: "Recently active", exact: true });
    const collapseAll = sidebar.getByRole("button", { name: "Collapse all", exact: true });
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
    await search.press("Escape");
    await collapseAll.click();
    await expect(toggle).toHaveAttribute("aria-pressed", "true");
    await sidebar.getByRole("button", { name: "Expand Navigation broker " + run, exact: true }).click();
    await expect(sidebar.getByRole("button", { name: "North room " + run + ", open", exact: true })).toBeVisible();
    await expect(sidebar.getByRole("button", { name: "South room " + run + ", open", exact: true })).toHaveCount(0);
    await sidebar.getByRole("button", { name: "Expand North room " + run, exact: true }).click();
    // A topic chain without branches ends in its reading, shown by display name.
    await expect(active).toBeVisible();
    await page.getByRole("navigation", { name: "Workspace", exact: true }).getByRole("link", { name: "Sources", exact: true }).click();
    await expect(toggle).toHaveAttribute("aria-pressed", "true");
    await expect.poll(() => page.evaluate(() => {
      const entry = Object.entries(localStorage).find(([key]) => key.startsWith("aberration:explorer:v1:"));
      return entry ? (JSON.parse(entry[1]) as { onlineOnly?: boolean }).onlineOnly : false;
    })).toBe(true);
    await page.reload();
    await expect(toggle).toHaveAttribute("aria-pressed", "true");
    await page.getByRole("button", { name: "Show collection " + collection.label, exact: true }).click();
    await expect(sidebar.getByText("In " + collection.label, { exact: true })).toBeVisible();
    await expect(active).toBeVisible();
    await expect(quiet).toHaveCount(0);
    for (const appearance of ["Light", "Dark"] as const) {
      await setAppearance(page, appearance);
      await sidebar.screenshot({ path: testInfo.outputPath("online-topics-" + appearance.toLowerCase() + ".png"), animations: "disabled" });
    }
    await toggle.click();
    await expect(quiet).toBeVisible();
    await toggle.click();
    clearInterval(publishTimer); publishTimer = undefined;
    await expect(sidebar.getByText("No recently active topics.", { exact: true })).toBeVisible({ timeout: 150_000 });
    const showAll = sidebar.getByRole("button", { name: "Show all topics", exact: true });
    await expect(showAll).toHaveCSS("text-decoration-line", "underline");
    await sidebar.locator(".ex-list-empty").screenshot({ path: testInfo.outputPath("no-active-topics.png") });
    await showAll.focus(); await showAll.press("Enter");
    await expect(toggle).toHaveAttribute("aria-pressed", "false");
    await expect(quiet).toBeVisible();
    await toggle.click();
    await expect(sidebar.getByText("No recently active topics.", { exact: true })).toBeVisible();
    await publisher.publishAsync(fixture.streams[0]!.topic, "24", { qos: 1 });
    await expect(active.locator("svg")).toHaveAttribute("fill", "currentColor");
    await page.setViewportSize({ width: 320, height: 844 });
    await page.getByRole("button", { name: "Show sidebar", exact: true }).click();
    await expect(toggle).toHaveAttribute("aria-pressed", "true");
    await toggle.scrollIntoViewIfNeeded();
    await expect(toggle).toBeInViewport();
    const box = await toggle.boundingBox();
    expect(box!.width).toBeGreaterThanOrEqual(44); expect(box!.height).toBeGreaterThanOrEqual(44);
    await expect(collapseAll).toBeInViewport();
    await expectNoHorizontalScroll(page);
    await page.screenshot({ path: testInfo.outputPath("online-topics-mobile.png"), animations: "disabled" });
    expect(previewStarts).toBe(0); expect(configurationWrites).toBe(0);
  } finally {
    clearInterval(publishTimer);
    await publisher?.endAsync();
    await fixture.cleanup();
  }
});

test("filters real recorded reports by device and reading across the shared sidebar", async ({ page }) => {
  const fixture = await createFixture(page, 2);
  const anomalies: string[] = [];
  let publisher: MqttClient | undefined;
  try {
    const applied = await page.request.put("/api/v1/recording", { headers: fixture.headers, data: {
      expected_revision: fixture.snapshot.revision, expected_collection_revision: fixture.snapshot.runtime.collection_revision,
      reading_ids: fixture.streams.map(stream => stream.id), policy: { mode: "original", interval_seconds: 10 },
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
    const recorded = async (readingId: string) => {
      const response = await page.request.get(`/api/v1/readings/${encodeURIComponent(readingId)}/measurements?limit=1`, { headers: fixture.headers });
      return response.ok() ? (await response.json() as unknown[]).length : 0;
    };
    await expect.poll(() => recorded(fixture.streams[0]!.id)).toBeGreaterThan(0);
    const names = ["North first " + fixture.north, "North second " + fixture.north, "South report " + fixture.south];
    for (const [position, stream] of fixture.streams.entries()) {
      await expect.poll(() => recorded(stream.id)).toBeGreaterThan(0);
      const response = await page.request.post("/api/v1/alarms", { headers: fixture.headers, data: {
        reading_ids: [stream.id], timestamp: new Date().toISOString(),
        alarm_type: names[position], value: .01, value_type: "tail_pvalue",
      } });
      expect(response.status(), await response.text()).toBe(201);
      anomalies.push((await response.json() as { alarm_id: string }).alarm_id);
    }
    const report = page.waitForResponse(response =>
      new URL(response.url()).pathname === "/api/v1/alarms/query");
    await page.goto("/anomalies");
    const response = await report;
    expect(response.ok(), await response.text()).toBe(true);
    expect((await response.json() as { items: unknown[] }).items).toEqual(expect.arrayContaining(
      anomalies.map(alarm_id => expect.objectContaining({ alarm_id })),
    ));
    const navigation = page.getByRole("navigation", { name: "Workspace", exact: true });
    const search = page.getByRole("searchbox", { name: "Search catalogue", exact: true });
    await search.fill(fixture.north);
    await page.getByRole("button", { name: "North room " + fixture.north.slice(-8) + ", open", exact: true }).click();
    await expect(page.getByRole("cell", { name: names[0], exact: true })).toBeVisible();
    await expect(page.getByRole("cell", { name: names[1], exact: true })).toBeVisible();
    await expect(page.getByRole("cell", { name: names[2], exact: true })).toHaveCount(0);
    await navigation.getByRole("link", { name: "Sources", exact: true }).click();
    const entityReadings = page.getByRole("region", { name: "Entity readings", exact: true });
    await expect(entityReadings).toBeVisible();
    await expect(page.getByRole("radiogroup", { name: "Recording", exact: true })).toHaveCount(0);
    await entityReadings.getByRole("button", { name: /North value 01/ }).click();
    await expect(page.getByRole("radio", { name: "Every message", exact: true })).toBeChecked();
    await navigation.getByRole("link", { name: "Reporting", exact: true }).click();
    await expect(page.getByRole("cell", { name: names[0], exact: true })).toBeVisible();
    await expect(page.getByRole("cell", { name: names[1], exact: true })).toHaveCount(0);
    await expect(page.getByRole("cell", { name: names[2], exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Show all sources", exact: true }).click();
    for (const name of names) await expect(page.getByRole("cell", { name, exact: true })).toBeVisible();
  } finally {
    await publisher?.endAsync();
    for (const id of anomalies) {
      const response = await page.request.delete("/api/v1/alarms/" + encodeURIComponent(id), { headers: fixture.headers });
      expect(response.ok(), await response.text()).toBe(true);
    }
    await fixture.cleanup();
  }
});
