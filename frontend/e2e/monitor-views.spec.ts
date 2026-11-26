import { expect, test, type Page } from "@playwright/test";
import { installSidebarMockApi } from "./helpers/sidebarMockApi";
import { fulfillJson } from "./helpers/detailsMockApi";

const COUNT = 600;
// Three monitors watch one reading; their anomalies overlap around the same disturbance.
const MONITORS = [
  { id: "monitor-a", name: "Drift", alarms: [[200, 232], [400, 404]] },
  { id: "monitor-b", name: "Spikes", alarms: [[214, 250], [480, 480]] },
  { id: "monitor-c", name: "Forecast", alarms: [[222, 240]] },
];

async function openReading(page: Page, theme: "light" | "dark", monitors = MONITORS) {
  const now = Date.now();
  const at = (index: number) => new Date(now - (COUNT - 1 - index) * 1000).toISOString();
  const points = Array.from({ length: COUNT }, (_, index) => ({ timestamp: at(index), created: at(index),
    value: 50 + Math.sin(index / 16) * 0.025 + Math.cos(index * 2) * 0.004 + (index >= 200 && index < 250 ? 0.03 : 0) }));
  const evidence = monitors.flatMap(monitor => points.slice(24).map((point, offset) => ({
    monitor_id: monitor.id, timestamp: point.timestamp, created: point.timestamp, sequence_number: offset + 1,
    reading_ids: ["frequency"], input_timestamps: { frequency: point.timestamp }, strategy: "adaptive_stream", model_type: "half_space_trees",
    anomaly_score: 1, threshold: 2, restarted_martingale: null,
    alarm: monitor.alarms.some(([first, last]) => offset + 24 >= first! && offset + 24 <= last!),
    detector_inputs: [{ detector_id: null, inputs: { frequency: point.value } }], forecasts: [],
  })));
  await installSidebarMockApi(page, { theme, favourites: [] });
  await page.route("**/v1/**", async route => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api(?=\/v1\/)/u, "");
    if (path === "/v1/catalogue") return fulfillJson(route, {
      revision: 1, can_edit: true, storage_origin: "saved",
      document: { format: "aberration-system", schema_version: 1, label: "Monitor views fixture", default_policy: { mode: "off" },
        brokers: [{ id: "broker", label: "Meter", host: "example.invalid", protocol: "mqtt", port: 1883, transport: "tcp", tls: false }],
        devices: [], groups: [], readings: [{ id: "frequency", label: "Frequency", broker_id: "broker", topic: "frequency",
          category: "Other", value_type: "number", unit: "Hz" }] },
      runtime: { mode: "collection", message: "", bindings: { frequency: { broker_id: "broker", policy: { mode: "original", interval_seconds: 1 } } } },
    });
    if (path === "/v1/monitors/overview") return fulfillJson(route, { authoring_enabled: false, monitors: monitors.map(monitor => ({
      id: monitor.id, display_name: monitor.name, reading_ids: ["frequency"], model_type: "half_space_trees",
      monitoring_strategy: "adaptive_stream", active: true,
      operational_status: { stage: "operational", is_stale: false, message_count: COUNT, processed_message_count: COUNT - 24, updated_at: at(COUNT - 1) },
    })) });
    if (path === "/v1/evidence/chart") return fulfillJson(route, url.searchParams.has("after_created") ? [] : evidence);
    if (path === "/v1/readings/frequency/measurements") return fulfillJson(route, url.searchParams.has("after_created") ? [] : [...points].reverse());
    if (path === "/v1/readings/frequency/measurements/buckets") return fulfillJson(route, { representation: "raw", points, interval_ms: 0,
      sample_count: points.length, extent: [points[0]!.timestamp, points[points.length - 1]!.timestamp] });
    return route.fallback();
  });
  await page.goto("/");
  await page.getByRole("searchbox", { name: "Search catalogue" }).fill("Frequency");
  await page.getByRole("button", { name: "Frequency, preview", exact: true }).click();
  return page.getByRole("region", { name: "Reading preview", exact: true }).getByRole("region", { name: "History", exact: true });
}

for (const theme of ["light", "dark"] as const) {
  test(`a reading's chart switches between raw data and its monitors in ${theme}`, async ({ page }, testInfo) => {
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.setViewportSize({ width: 1440, height: 1200 });
    const history = await openReading(page, theme);
    const views = history.getByRole("group", { name: "Chart view", exact: true });
    await expect(views.getByRole("button")).toHaveText(["Raw data", "Drift", "Spikes", "Forecast"]);
    // Until a view is chosen the first running monitor has the chart, and the strip shows only its anomalies.
    await expect(views.getByRole("button", { name: "Drift", exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(history.getByRole("img", { name: "Anomalies: Drift 2", exact: true })).toBeVisible();
    await history.screenshot({ path: testInfo.outputPath(`monitor-${theme}.png`) });

    await views.getByRole("button", { name: "Raw data", exact: true }).click();
    const strip = history.getByRole("img", { name: "Anomalies: Drift 2, Spikes 2, Forecast 1", exact: true });
    await expect(strip).toBeVisible();
    await expect(history.getByText("Adaptive detector")).toHaveCount(0);
    await history.screenshot({ path: testInfo.outputPath(`raw-${theme}.png`) });

    // The pointer is a lens: over the stretch all three share, each monitor gets a field, and its name shows.
    const box = (await strip.boundingBox())!;
    // The strip begins where the plot does: at the gutter the chart measured for its value labels, a multiple of eight.
    const plot = (await history.locator("canvas").first().boundingBox())!;
    expect(box.x - plot.x).toBeGreaterThan(0);
    expect((box.x - plot.x) % 8).toBe(0);
    const shared = box.x + box.width * (231 / (COUNT - 1));
    await page.mouse.move(shared, box.y + box.height / 2);
    await expect(views.locator(".is-aimed")).toHaveCount(1);
    await history.screenshot({ path: testInfo.outputPath(`lens-${theme}.png`) });
    const aimed = (await views.locator(".is-aimed").textContent())!;
    await page.mouse.down();
    await page.mouse.up();
    await expect(views.getByRole("button", { name: aimed, exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(history.getByRole("img", { name: new RegExp(`^Anomalies: ${aimed} \\d$`) })).toBeVisible();

    await page.setViewportSize({ width: 390, height: 844 });
    const select = history.getByRole("combobox", { name: "Chart view", exact: true });
    await expect(select).toHaveValue(MONITORS.find(monitor => monitor.name === aimed)!.id);
    await select.selectOption("raw");
    await expect(strip).toBeVisible();
    await history.scrollIntoViewIfNeeded();
    await history.screenshot({ path: testInfo.outputPath(`raw-${theme}-mobile.png`) });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    expect(errors).toEqual([]);
  });
}

test("a reading without monitors has neither views nor an anomaly strip", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  const history = await openReading(page, "light", []);
  await expect(history.locator("canvas")).toBeVisible();
  await expect(history.getByRole("group", { name: "Chart view" })).toHaveCount(0);
  await expect(history.getByRole("img", { name: /anomalies/i })).toHaveCount(0);
});
