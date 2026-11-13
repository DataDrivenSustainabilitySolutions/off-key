import { mkdir } from "node:fs/promises";
import { expect, test, type Locator, type Page, type TestInfo } from "@playwright/test";
import { openPreferences, setAppearance } from "./helpers/appearance";
import { expectNoHorizontalScroll } from "./helpers/layout";
import { installSidebarMockApi } from "./helpers/sidebarMockApi";

// Route-mocked: the sidebar journeys need only the frontend and change no stored data.
test.use({ storageState: { cookies: [], origins: [] }, contextOptions: { reducedMotion: "reduce" } });

test("settings open after session loading, reloads and sidebar breakpoint changes", async ({ page }) => {
  await installSidebarMockApi(page);
  // A delayed session exposes the gap between navigation finishing and the
  // account control rendering, as in the production deployment journeys.
  await page.route("**/v1/me", async route => {
    await new Promise(resolve => setTimeout(resolve, 250));
    await route.fallback();
  });
  await page.goto("/sources");
  await setAppearance(page, "Dark");
  await page.reload();
  await setAppearance(page, "Light");
  for (const width of [390, 1600, 320, 844]) {
    await page.setViewportSize({ width, height: 844 });
    await setAppearance(page, "Dark");
    await expect(page.locator("html")).toHaveClass("dark");
  }
  await page.getByRole("button", { name: "Hide sidebar", exact: true }).click();
  const settings = await openPreferences(page);
  await expect(settings).toBeVisible();
  await settings.getByRole("button", { name: "Close settings", exact: true }).click();
  await expect(page.getByRole("button", { name: "Account menu", exact: true })).toBeFocused();
});

async function bounds(locator: Locator) {
  const box = await locator.boundingBox();
  expect(box).not.toBeNull();
  return box!;
}

/** Saves a screenshot with the test, and also in SIDEBAR_SCREENSHOT_DIR when that is set. */
async function capture(page: Page, testInfo: TestInfo, name: string) {
  await page.screenshot({ path: testInfo.outputPath(`${name}.png`), animations: "disabled" });
  const directory = process.env.SIDEBAR_SCREENSHOT_DIR;
  if (directory) {
    await mkdir(directory, { recursive: true });
    await page.screenshot({ path: `${directory}/${name}.png`, animations: "disabled" });
  }
}

/** Neither the page nor the sidebar scrolls sideways. */
async function expectNoSidebarOverflow(page: Page) {
  await expectNoHorizontalScroll(page);
  for (const element of await page.locator(".app-sidebar, .app-sidebar-body, .ex-list-scroll").all()) {
    if (!await element.isVisible()) continue;
    expect(await element.evaluate(node => node.scrollWidth <= node.clientWidth + 1)).toBe(true);
  }
}

test("one sidebar holds workspaces, saved items, the catalogue tree and account controls", async ({ page }, testInfo) => {
  const api = await installSidebarMockApi(page);
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/sources");
  const sidebar = page.getByRole("complementary", { name: "Sidebar", exact: true });
  const workspaces = sidebar.getByRole("navigation", { name: "Workspace", exact: true });
  const catalogue = sidebar.getByRole("navigation", { name: "Catalogue", exact: true });
  const main = page.locator(".app-main");
  const footer = sidebar.locator(".app-sidebar-footer");
  await expect(catalogue.getByRole("button", { name: "Building broker, open", exact: true })).toBeVisible();

  // No horizontal navigation bar competes with the sidebar.
  await expect(page.getByTestId("application-header")).toHaveCount(0);
  await expect(page.getByRole("navigation", { name: "Primary navigation", exact: true })).toHaveCount(0);
  expect(await workspaces.getByRole("link").allTextContents()).toEqual(["Monitoring", "Sources", "Reporting", "Dojo"]);
  await expect(workspaces.getByRole("link", { name: "Sources", exact: true })).toHaveAttribute("aria-current", "page");
  for (const category of ["Favourites", "Collections"]) await expect(sidebar.getByRole("region", { name: category, exact: true })).toBeVisible();
  expect((await bounds(sidebar)).width).toBe(264);
  expect((await bounds(main)).x).toBe(264);
  const sidebarRow = await bounds(workspaces.getByRole("link", { name: "Monitoring", exact: true }));
  expect(sidebarRow.height).toBeGreaterThanOrEqual(32);
  expect(sidebarRow.height).toBeLessThanOrEqual(36);

  // A long branch scrolls inside the catalogue; the footer stays in view.
  await catalogue.getByRole("button", { name: "Expand Laboratory broker with a deliberately long name for truncation", exact: true }).click();
  await catalogue.getByRole("button", { name: "Expand lab/benches", exact: true }).click();
  const list = catalogue.locator(".ex-list-scroll");
  const last = catalogue.getByRole("button", { name: "Bench 240 supply voltage, preview", exact: true });
  // Measured rows can change the list's height while it scrolls; keep going to the end.
  await expect.poll(async () => {
    await list.evaluate(element => { element.scrollTop = element.scrollHeight; });
    return last.isVisible();
  }).toBe(true);
  expect(await catalogue.locator("li").count()).toBeLessThan(60);
  const footerBox = await bounds(footer);
  expect(footerBox.y + footerBox.height).toBeLessThanOrEqual(800);
  await expect(footer.getByRole("button", { name: "Account menu", exact: true })).toBeInViewport();
  await expectNoSidebarOverflow(page);

  // Search finds the full MQTT path, shows where each result sits and leaves the selection alone.
  const url = page.url();
  await page.keyboard.press("ControlOrMeta+k");
  const search = catalogue.getByRole("searchbox", { name: "Search catalogue", exact: true });
  await expect(search).toBeFocused();
  await search.fill("lab/benches/120");
  const result = catalogue.getByRole("button", { name: "Bench 120 supply voltage, preview", exact: true });
  await expect(result).toContainText("lab/benches/120/supply/voltage");
  expect(page.url()).toBe(url);
  await page.keyboard.press("ArrowDown");
  await expect(result).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/source=/);
  await expect(search).toHaveValue("lab/benches/120");
  await search.focus();
  await page.keyboard.press("Escape");
  await expect(search).toHaveValue("");
  // The tree returns as it was left, with the chosen reading revealed among its siblings.
  await expect(catalogue.getByRole("list", { name: "Catalogue items", exact: true })).toBeVisible();
  await expect(catalogue.getByRole("button", { name: "Bench 120 supply voltage, preview", exact: true })).toHaveAttribute("aria-current", "true");
  await expect(catalogue.getByRole("button", { name: "Bench 119 supply voltage, preview", exact: true })).toBeVisible();

  // Back restores the earlier selection; the sidebar stays mounted.
  const sidebarHandle = await sidebar.elementHandle();
  await page.goBack();
  await expect(page).toHaveURL(url);
  expect(await sidebarHandle!.evaluate(element => element.isConnected)).toBe(true);

  // Width and visibility persist for the account.
  const edge = page.getByRole("separator", { name: "Resize sidebar", exact: true });
  await edge.focus();
  await page.keyboard.press("Shift+ArrowRight");
  await expect.poll(async () => (await bounds(sidebar)).width).toBe(328);
  await page.reload();
  await expect.poll(async () => (await bounds(sidebar)).width).toBe(328);
  await expect(catalogue.getByRole("button", { name: "Collapse lab/benches", exact: true })).toBeAttached();
  await edge.focus();
  await page.keyboard.press("Home");
  await expect.poll(async () => (await bounds(sidebar)).width).toBe(224);
  await edge.dblclick();
  await expect.poll(async () => (await bounds(sidebar)).width).toBe(264);

  for (const appearance of ["Light", "Dark"] as const) {
    await setAppearance(page, appearance);
    await catalogue.locator(".ex-list-scroll").evaluate(element => { element.scrollTop = 0; });
    await capture(page, testInfo, `sidebar-desktop-${appearance.toLowerCase()}`);
  }

  const expandedMain = await bounds(main);
  const heading = page.getByRole("heading", { name: "Sources", exact: true });
  const expandedHeading = await bounds(heading);
  await sidebar.getByRole("button", { name: "Hide sidebar", exact: true }).click();
  const show = page.getByRole("button", { name: "Show sidebar", exact: true });
  await expect(show).toBeFocused();
  await expect(sidebar).toHaveAttribute("inert", "");
  await expect.poll(async () => (await bounds(main)).x).toBe(0);
  expect((await bounds(main)).width).toBe(1280);
  expect((await bounds(main)).y).toBe(expandedMain.y);
  expect((await bounds(main)).height).toBe(expandedMain.height);
  expect((await bounds(heading)).y).toBe(expandedHeading.y);
  await capture(page, testInfo, "sidebar-collapsed-dark");
  await page.reload();
  await expect(show).toBeVisible();
  await show.click();
  await expect(sidebar.getByRole("button", { name: "Hide sidebar", exact: true })).toBeFocused();
  expect((await bounds(main)).y).toBe(expandedMain.y);
  expect((await bounds(heading)).y).toBe(expandedHeading.y);
  await setAppearance(page, "Light");
  // Browsing, searching and expanding never wrote anything.
  expect(api.writes).toEqual([]);
});

test("a chosen source scopes the page while the chart keeps its full workspace", async ({ page }, testInfo) => {
  const api = await installSidebarMockApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  const sidebar = page.getByRole("complementary", { name: "Sidebar", exact: true });
  await sidebar.getByRole("region", { name: "Favourites", exact: true }).getByRole("button", { name: "Air temperature", exact: true }).click();
  const preview = page.getByRole("region", { name: "Reading preview", exact: true });
  await expect(preview).toBeVisible();
  // The favourite and its tree row both show the selection; the workspace link keeps its own state.
  await expect(sidebar.getByRole("button", { name: "Air temperature, preview", exact: true })).toHaveAttribute("aria-current", "true");
  await expect(sidebar.getByRole("link", { name: "Monitoring", exact: true })).toHaveAttribute("aria-current", "page");
  const sidebarBox = await bounds(sidebar);
  expect((await bounds(preview)).x).toBeGreaterThanOrEqual(sidebarBox.x + sidebarBox.width);
  await expectNoSidebarOverflow(page);
  // Collections narrow the tree without changing what the page shows.
  const url = page.url();
  await sidebar.getByRole("button", { name: "Show collection Lab benches", exact: true }).click();
  await expect(sidebar.getByText("In Lab benches")).toBeVisible();
  expect(page.url()).toBe(url);
  await capture(page, testInfo, "sidebar-selection-collection");
  await sidebar.getByRole("button", { name: "Show every source", exact: true }).click();
  // Workspace links carry the selected source to the next page.
  await sidebar.getByRole("link", { name: "Reporting", exact: true }).click();
  await expect(page).toHaveURL(/\/anomalies\?source=/);
  await sidebar.getByRole("link", { name: "Dojo", exact: true }).click();
  await expect(page.getByRole("main", { name: "Dojo workspace", exact: true })).toBeVisible();
  expect((await bounds(page.getByRole("main", { name: "Dojo workspace", exact: true }))).x).toBeGreaterThanOrEqual(sidebarBox.width);
  expect(api.writes).toEqual([]);
});

test("phones use one focus-trapped drawer that closes on navigation and returns focus", async ({ page }, testInfo) => {
  await installSidebarMockApi(page);
  for (const width of [320, 390]) {
    await page.setViewportSize({ width, height: 844 });
    await page.goto("/");
    const show = page.getByRole("button", { name: "Show sidebar", exact: true });
    await expect(show).toBeVisible();
    await expect(page.getByRole("complementary", { name: "Sidebar", exact: true })).toHaveCount(0);
    await expect(page.getByRole("separator", { name: "Resize sidebar", exact: true })).toHaveCount(0);
    const showBox = await bounds(show);
    expect(showBox.width).toBeGreaterThanOrEqual(44);
    const main = page.locator(".app-main");
    const initialMain = await bounds(main);
    const heading = page.getByRole("heading", { name: "Monitoring", exact: true });
    await expect(heading).toBeVisible();
    expect((await bounds(heading)).y).toBeGreaterThanOrEqual(showBox.y + showBox.height);
    await expectNoHorizontalScroll(page);

    await show.click();
    const drawer = page.getByRole("dialog", { name: "Navigation", exact: true });
    await expect(drawer).toBeFocused();
    const drawerBox = await bounds(drawer);
    expect(drawerBox.x + drawerBox.width).toBeLessThan(width);
    expect(await bounds(main)).toEqual(initialMain);
    await expect(drawer.getByRole("button", { name: "Account menu", exact: true })).toBeInViewport();
    const close = drawer.getByRole("button", { name: "Close navigation", exact: true });
    await close.focus();
    await page.keyboard.press("Shift+Tab");
    expect(await drawer.evaluate(element => element.contains(document.activeElement))).toBe(true);
    await page.keyboard.press("Escape");
    await expect(drawer).toHaveCount(0);
    await expect(show).toBeFocused();

    await page.keyboard.press("ControlOrMeta+k");
    await expect(drawer.getByRole("searchbox", { name: "Search catalogue", exact: true })).toBeFocused();
    await close.click();
    await expect(drawer).toHaveCount(0);
    await expect(show).toBeFocused();
    await show.click();
    await drawer.getByRole("link", { name: "Reporting", exact: true }).click();
    await expect(drawer).toHaveCount(0);
    await expect(page).toHaveURL(/\/anomalies/);
    await expectNoHorizontalScroll(page);
  }
  for (const appearance of ["Light", "Dark"] as const) {
    await setAppearance(page, appearance);
    await page.getByRole("button", { name: "Show sidebar", exact: true }).click();
    const drawer = page.getByRole("dialog", { name: "Navigation", exact: true });
    const expand = drawer.getByRole("button", { name: "Expand Building broker", exact: true });
    if (await expand.count()) await expand.click();
    // The drawer's middle scrolls as one, bringing the catalogue up under saved items.
    await drawer.locator(".app-sidebar-body").evaluate(element => { element.scrollTop = element.scrollHeight; });
    await expect(drawer.getByRole("button", { name: "Account menu", exact: true })).toBeInViewport();
    await capture(page, testInfo, `sidebar-mobile-${appearance.toLowerCase()}`);
    await page.keyboard.press("Escape");
  }
  await setAppearance(page, "Light");
});

test("read-only, empty and unavailable catalogues keep a coherent sidebar", async ({ page, browser }, testInfo) => {
  await installSidebarMockApi(page, { role: "viewer", favourites: [] });
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.goto("/sources");
  const sidebar = page.getByRole("complementary", { name: "Sidebar", exact: true });
  await expect(sidebar.getByRole("button", { name: "Building broker, open", exact: true })).toBeVisible();
  expect(await sidebar.getByRole("navigation", { name: "Workspace", exact: true }).getByRole("link").allTextContents())
    .toEqual(["Monitoring", "Sources", "Reporting"]);
  await expect(sidebar.getByRole("region", { name: "Favourites", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Add broker", exact: true })).toHaveCount(0);

  const empty = await browser.newPage();
  await installSidebarMockApi(empty, { catalogue: null, favourites: [] });
  await empty.setViewportSize({ width: 1280, height: 720 });
  await empty.goto("/");
  const emptySidebar = empty.getByRole("complementary", { name: "Sidebar", exact: true });
  await expect(emptySidebar.getByText("No sources yet.")).toBeVisible();
  await expect(emptySidebar.getByRole("region", { name: "Collections", exact: true })).toHaveCount(0);
  await capture(empty, testInfo, "sidebar-empty-catalogue");
  await emptySidebar.getByRole("button", { name: "Open catalogue settings", exact: true }).click();
  await expect(empty.getByRole("dialog", { name: "Settings", exact: true }).getByRole("heading", { name: "Catalogue", level: 2 })).toBeVisible();
  await empty.close();

  const failing = await browser.newPage();
  await installSidebarMockApi(failing, { catalogueError: true });
  await failing.goto("/");
  await expect(failing.getByRole("complementary", { name: "Sidebar", exact: true }).getByRole("alert")).toContainText("could not be loaded");
  await expect(failing.getByRole("button", { name: "Account menu", exact: true })).toBeVisible();
  await failing.close();
});

test("dense source history offers automatic means and immediate raw readings", async ({ page }, testInfo) => {
  const now = Date.parse("2026-11-11T18:30:00Z");
  await page.clock.setFixedTime(now);
  await page.setViewportSize({ width: 1440, height: 1080 });
  const broker = { id: "demo", label: "Demo source", host: "demo.example.invalid", protocol: "mqtt", port: 1883, transport: "tcp", tls: false };
  const document = { format: "aberration-system", schema_version: 1, label: "Demo", default_policy: { mode: "off" },
    brokers: [broker], devices: [{ id: "charger", label: "Demo charger", broker_id: "demo", kind: "charger" }],
    readings: [{ id: "voltage", label: "Voltage DC", broker_id: "demo", device_id: "charger", topic: "demo/voltage", value_type: "number", unit: "V", category: "Voltage" }], groups: [] };
  await installSidebarMockApi(page, { favourites: [], theme: "light" });
  const points = Array.from({ length: 3600 }, (_, i) => ({ timestamp: new Date(now - (3599 - i) * 1000).toISOString(),
    value: ((i * 1664525 + 1013904223) >>> 0) % 100 < 40 + 20 * Math.sin(i / 400) ? .1 : 0 }));
  const requests: URL[] = [];
  await page.route("**/v1/catalogue", route => route.fulfill({ json: { document, revision: 3, can_edit: true, storage_origin: "saved",
    runtime: { mode: "collection", message: "", bindings: { voltage: { broker_id: "demo", device_id: "charger", policy: { mode: "original", interval_seconds: 1 } } } } } }));
  await page.route(/\/v1\/readings\/voltage\/measurements(?:\/buckets)?(?:\?|$)/, route => {
    const url = new URL(route.request().url());
    if (!url.pathname.endsWith("/buckets")) return route.fulfill({ json: url.searchParams.has("after_created") ? [] : points.slice(-1000).map(point => ({ ...point, created: point.timestamp })).reverse() });
    requests.push(url);
    const start = Date.parse(url.searchParams.get("start") ?? points[0]!.timestamp);
    const end = Date.parse(url.searchParams.get("end") ?? new Date(now).toISOString());
    const visible = points.filter(point => Date.parse(point.timestamp) >= start && Date.parse(point.timestamp) <= end);
    const raw = url.searchParams.get("view") === "raw" || visible.length < 200;
    const interval = Number(url.searchParams.get("window_ms") ?? 30000);
    const grouped = new Map<number, typeof points>();
    for (const point of visible) {
      const time = Math.floor(Date.parse(point.timestamp) / interval) * interval;
      grouped.set(time, [...(grouped.get(time) ?? []), point]);
    }
    return route.fulfill({ json: { representation: raw ? "raw" : "mean", points: raw ? visible : [...grouped].map(([time, values]) => ({
      timestamp: new Date(time + interval / 2).toISOString(), value: values.reduce((sum, point) => sum + point.value, 0) / values.length,
      minimum: Math.min(...values.map(point => point.value)), maximum: Math.max(...values.map(point => point.value)), count: values.length,
      start: new Date(time).toISOString(), end: new Date(time + interval).toISOString(),
    })), interval_ms: raw ? 0 : interval, sample_count: visible.length,
    extent: visible.length ? [visible[0]!.timestamp, visible[visible.length - 1]!.timestamp] : null, truncated: false } });
  });
  await page.goto("/");
  await page.getByRole("searchbox", { name: "Search catalogue" }).fill("Voltage DC");
  await page.getByRole("button", { name: "Voltage DC, preview", exact: true }).click();
  const preview = page.getByRole("region", { name: "Reading preview", exact: true });
  const history = preview.getByRole("region", { name: "History", exact: true });
  const averaging = history.getByRole("button", { name: "Automatic averaging", exact: true });
  await expect(averaging).toHaveAttribute("aria-pressed", "true");
  await expect.poll(() => requests.at(-1)?.searchParams.get("view")).toBe("auto");
  await expect(history.locator("canvas")).toBeVisible();
  await averaging.hover();
  await expect(page.getByRole("tooltip")).toContainText("30s mean · min–max");
  await page.keyboard.press("Escape");
  await history.getByRole("heading", { name: "History", exact: true }).hover();
  await expect(page.getByRole("tooltip")).toHaveCount(0);
  await capture(page, testInfo, "timeline-minimal-light");
  await preview.screenshot({ path: testInfo.outputPath("timeline-minimal-detail.png"), animations: "disabled" });
  if (process.env.SIDEBAR_SCREENSHOT_DIR) await preview.screenshot({ path: `${process.env.SIDEBAR_SCREENSHOT_DIR}/timeline-minimal-detail.png`, animations: "disabled" });
  await history.getByRole("button", { name: "Zoom in", exact: true }).click();
  await expect.poll(() => requests.at(-1)?.searchParams.has("end")).toBe(true);
  const inspectedStart = requests.at(-1)!.searchParams.get("start");
  const inspectedEnd = requests.at(-1)!.searchParams.get("end");
  await averaging.click();
  await expect(averaging).toHaveAttribute("aria-pressed", "false");
  await expect.poll(() => requests.at(-1)?.searchParams.get("view")).toBe("raw");
  expect(requests.at(-1)!.searchParams.get("start")).toBe(inspectedStart);
  expect(requests.at(-1)!.searchParams.get("end")).toBe(inspectedEnd);
  await history.getByText(/^Values ·/).click();
  await expect(history.getByRole("table")).toBeVisible();
  await expect(history.getByText("Measured at (UTC)", { exact: true })).toBeVisible();
  await averaging.click();
  await expect(averaging).toHaveAttribute("aria-pressed", "true");
  await expect.poll(() => requests.at(-1)?.searchParams.get("view")).toBe("auto");
  await page.setViewportSize({ width: 390, height: 844 });
  await expectNoHorizontalScroll(page);
});
