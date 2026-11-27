import { expect, test, type Locator, type Page } from "@playwright/test";

import { zoomChart } from "./helpers/chart";
import { setAppearance } from "./helpers/appearance";
import { fulfillJson, installDetailsMockApi } from "./helpers/detailsMockApi";

const DEVICE_ID = "e2e-tandem";
const SENSOR = "systemVoltage";
const BASE_TIME = Date.parse("2026-07-28T08:00:00.000Z");
const timestamp = (seconds: number) =>
  new Date(BASE_TIME + seconds * 1_000).toISOString();
type EvidenceMode = "static" | "adaptive" | "mixed";
type Theme = "light" | "dark";

const telemetry = [0, 60, 120, 180, 240].map((seconds, index) => ({
  timestamp: timestamp(seconds),
  created: timestamp(seconds + 1),
  value: [229.8, 230.4, 231.1, 230.7, 232.2][index],
}));

const tracker = (
  trackerId: string,
  value: number | null,
  threshold: number,
  overflow = false,
) => ({
  tracker_id: trackerId,
  betting_function: "power",
  betting_parameters: { epsilon: 0.5 },
  alarm_statistic: "restarted_martingale",
  statistic_value: value,
  statistic_is_infinite: overflow,
  log_statistic_value: overflow ? 1_000 : Math.log(value ?? 1),
  statistics: {},
  e_value: 1,
  e_value_is_infinite: false,
  log_e_value: 0,
  threshold,
  alarm_fired: overflow,
  alarm_active: overflow,
  alarm_count: Number(overflow),
  tested_count: 1,
});

const staticEvidence = [0, 120, 180, 240].map((seconds, index) => ({
  strategy: "static_baseline",
  monitor_id: "static-service",
  timestamp: timestamp(seconds),
  created: timestamp(seconds + 30),
  sequence_number: index + 1,
  reading_ids: [SENSOR],
  input_timestamps: { [SENSOR]: timestamp(seconds) },
  restarted_martingale: index === 3 ? null : [1, 0.1, 10][index],
  restarted_martingale_is_infinite: index === 3,
  log_restarted_martingale: index === 3 ? 1_000 : 0,
  threshold: index < 2 ? 100 : 150,
  alarm: index === 3,
  tracker_results: [
    tracker("secondary", index + 2, 8),
    tracker("primary", index === 3 ? null : [1, 0.1, 10][index]!, index < 2 ? 100 : 150, index === 3),
  ],
}));

const adaptiveRow = (serviceId: string, seconds: number, sequence: number) => ({
  strategy: "adaptive_stream",
  monitor_id: serviceId,
  timestamp: timestamp(seconds),
  created: timestamp(seconds + 30),
  sequence_number: sequence,
  reading_ids: [SENSOR],
  input_timestamps: { [SENSOR]: timestamp(seconds) },
  anomaly_score: serviceId === "adaptive-a" ? [-2, 1, 7][sequence - 1] : sequence + 1,
  restarted_martingale: null,
  threshold: sequence < 3 ? 4 : 2,
  alarm: sequence === 3,
});

const adaptiveEvidence = [
  ...[0, 120, 240].map((seconds, index) => adaptiveRow("adaptive-a", seconds, index + 1)),
  ...[0, 180].map((seconds, index) => adaptiveRow("adaptive-z", seconds, index + 1)),
];

const alarm = (alarmId: string, seconds: number, readingIds: string[], alarmType: string, value: number) => ({
  alarm_id: alarmId,
  timestamp: timestamp(seconds),
  device_id: DEVICE_ID,
  device_label: DEVICE_ID,
  reading_ids: readingIds,
  reading_labels: Object.fromEntries(readingIds.map(id => [id, id])),
  multivariate: readingIds.length > 1,
  alarm_type: alarmType,
  value,
  value_type: readingIds.length > 1 ? "conformal_pvalue" : "tail_pvalue",
  monitor_id: null,
});
const anomalies = [
  alarm("coincident-a", 1, [SENSOR], "spike", 0.01),
  alarm("coincident-b", 1, [SENSOR, "systemCurrent"], "multivariate", 0.02),
  alarm("unmatched", 40, [SENSOR], "drift", 0.005),
];

const installMockApi = async (
  page: Page,
  mode: EvidenceMode,
  theme: Theme,
  sensors: string[] = [SENSOR],
) => installDetailsMockApi(page, {
  deviceId: DEVICE_ID, sensors, theme, telemetry,
  laterTelemetry: [{ timestamp: timestamp(300), created: timestamp(301), value: 233 }],
  evidence: mode === "static" ? staticEvidence : mode === "adaptive" ? adaptiveEvidence : [...staticEvidence, ...adaptiveEvidence],
  laterEvidence: mode === "static" ? [] : [adaptiveRow("adaptive-z", 300, 3)],
  anomalies: [...anomalies, anomalies[0]],
});

type PixelGlyph = { count: number; left: number; right: number; top: number; bottom: number };
type CanvasReadout = {
  width: number;
  height: number;
  /** Translucent red: the shading a threshold region used to put on every crossing. */
  wash: number;
  /** Opaque red: an alarm, an alarmed overflow marker or a red event. */
  red: PixelGlyph;
  /** Opaque red markers in the reading pane, such as an event's triangle. */
  topRed: PixelGlyph;
  orange: PixelGlyph;
  /** The reading's own line, which spans the shared time axis. */
  reading: PixelGlyph;
};

// Inspect visible Canvas pixels only, so the same regression runs against Vite
// and the deployed, bundled frontend without an application test hook.
const readCanvas = (chart: Locator): Promise<CanvasReadout> => chart.evaluate((container) => {
  const canvas = container.querySelector("canvas");
  if (!canvas) throw new Error("Chart Canvas unavailable");
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Chart Canvas context unavailable");
  const { width, height } = canvas;
  const scaleX = width / canvas.clientWidth;
  const scaleY = height / canvas.clientHeight;
  const pixels = context.getImageData(0, 0, width, height).data;
  const glyph = () => ({ count: 0, left: width, right: 0, top: height, bottom: 0 });
  const add = (target: ReturnType<typeof glyph>, x: number, y: number) => {
    target.count += 1;
    target.left = Math.min(target.left, x);
    target.right = Math.max(target.right, x);
    target.top = Math.min(target.top, y);
    target.bottom = Math.max(target.bottom, y);
  };
  const red = glyph(), topRed = glyph(), orange = glyph(), reading = glyph();
  let wash = 0;
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const offset = (y * width + x) * 4;
      const [r, g, b, a] = [pixels[offset]!, pixels[offset + 1]!, pixels[offset + 2]!, pixels[offset + 3]!];
      if (a >= 18 && a <= 60 && r > g + 40 && Math.abs(g - b) < 12) wash += 1;
      if (a >= 170 && r > g + 40 && Math.abs(g - b) < 20) {
        add(red, x, y);
        // Event markers are opaque; the translucent alarm-onset rule and the legend above the panes are not markers.
        if (y < height / 3 && y > 40 * scaleY && a >= 200) add(topRed, x, y);
      }
      if (a >= 140 && r > g + 60 && g > b + 60) add(orange, x, y);
      // Below the legend, whose swatch shares the reading's colour.
      if (a >= 170 && g > r + 60 && b > r + 40 && y > 40 * scaleY) add(reading, x, y);
    }
  }
  const normalize = (item: ReturnType<typeof glyph>) => ({ count: item.count,
    left: item.count ? item.left / scaleX : 0, right: item.right / scaleX,
    top: item.count ? item.top / scaleY : 0, bottom: item.bottom / scaleY });
  return { width: canvas.clientWidth, height: canvas.clientHeight, wash,
    red: normalize(red), topRed: normalize(topRed), orange: normalize(orange), reading: normalize(reading) };
});

test.use({ video: "off", trace: "off" });

test.describe("Tandem anomaly chart regression", () => {
  test.use({
    storageState: { cookies: [], origins: [] },
    timezoneId: "UTC", colorScheme: "light", reducedMotion: "reduce",
    viewport: { width: 1440, height: 1100 },
  });

  for (const mode of ["static", "adaptive", "mixed"] as const) {
    for (const theme of ["light", "dark"] as const) {
      test(`${mode} evidence shows red only where the monitor alarmed, in ${theme} at desktop and narrow widths`, async ({ page }, testInfo) => {
        await installMockApi(page, mode, theme);
        await page.goto(`/details/${DEVICE_ID}`);
        const chart = page.getByTestId("telemetry-echart");
        const card = page.locator('[data-slot="card"]').filter({ has: chart });
        await expect(chart).toBeVisible();
        await expect(chart.locator("canvas")).toHaveCount(1);
        await expect(chart).toHaveAttribute("aria-label", mode === "mixed"
          ? /1 logarithmic static-evidence series.*1 adaptive score series relative to its threshold/u
          : mode === "static" ? /1 logarithmic static-evidence series/u : /1 adaptive score series relative to its threshold/u);
        if (mode !== "adaptive") {
          await expect(card.getByText(/beyond numeric range/iu)).toBeVisible();
        }
        await expect(card.getByText(/Shaded values|unshaded gaps|threshold unavailable/iu)).toHaveCount(0);
        await expect(chart).toHaveAttribute("aria-label", /Red marks where the monitor alarmed/u);

        for (const width of [1440, 390, 320]) {
          await page.setViewportSize({ width, height: width === 1440 ? 1100 : 1000 });
          await card.scrollIntoViewIfNeeded();
          // Each mode alarms once, on its last result: a rule marks it, and no threshold region is shaded
          // although the scores cross their thresholds without an alarm before it.
          await expect.poll(async () => (await readCanvas(chart)).red.count).toBeGreaterThan(10);
          const pixels = await readCanvas(chart);
          // Antialiased edges of the red line leave a few hundred faint pixels at most; a shaded region left thousands.
          expect(pixels.wash).toBeLessThan(400);
          expect(pixels.red.right).toBeGreaterThan(pixels.reading.right - 12);
          const box = await chart.boundingBox();
          expect(box).not.toBeNull();
          expect(box!.width).toBeLessThanOrEqual(width);
          expect(box!.width).toBeGreaterThan(width === 320 ? 200 : 250);
          expect(await card.evaluate((element) => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1);
          const screenshotPath = testInfo.outputPath(`${mode}-${theme}-${width}.png`);
          await card.screenshot({ path: screenshotPath });
          await testInfo.attach(`${mode} ${theme} ${width}px`, { path: screenshotPath, contentType: "image/png" });
        }
      });
    }
  }

  test("detector controls support keyboard focus and retain selection through polling, zoom, and theme changes", async ({ page }) => {
    const api = await installMockApi(page, "mixed", "light");
    await page.goto(`/details/${DEVICE_ID}`);
    const chart = page.getByTestId("telemetry-echart");
    const card = page.locator('[data-slot="card"]').filter({ has: chart });
    const staticDetector = card.getByRole("combobox", { name: "Static detector" });
    const adaptiveDetector = card.getByRole("combobox", { name: "Adaptive detector" });
    await expect(staticDetector).toBeVisible();
    await expect(adaptiveDetector).toBeVisible();
    await expect(staticDetector).toHaveValue("martingale:static-service:primary");
    await expect(adaptiveDetector.locator("option:checked")).toContainText("adaptive-a");
    await staticDetector.focus();
    await expect(staticDetector).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(adaptiveDetector).toBeFocused();
    await adaptiveDetector.selectOption("adaptive-score:adaptive-z");
    await expect(adaptiveDetector.locator("option:checked")).toContainText("adaptive-z");
    const selected = await adaptiveDetector.inputValue();
    await expect(card.getByText(/score 3, threshold 4/u)).toBeVisible();
    await expect(card.getByText(/score 7/u)).toHaveCount(0);
    await zoomChart(page, card);
    await api.publish();
    await expect(card.getByText("New data available")).toBeVisible();
    await expect(adaptiveDetector).toHaveValue(selected);
    await expect(card.getByRole("button", { name: "Return to live" })).toBeVisible();
    await setAppearance(page, "Dark");
    await expect(page.locator("html")).toHaveClass(/dark/u);
    await expect(adaptiveDetector).toHaveValue(selected);
    await expect(card.getByRole("button", { name: "Return to live" })).toBeVisible();
    await card.getByRole("button", { name: "Past hour" }).click();
    await expect(adaptiveDetector).toHaveValue(selected);
    await expect(card.getByRole("button", { name: "Return to live" })).toBeHidden();
  });

  test("event details keep coincident events and unmatched timestamps inspectable by keyboard", async ({ page }) => {
    await installMockApi(page, "mixed", "light");
    await page.goto(`/details/${DEVICE_ID}`);
    const chart = page.getByTestId("telemetry-echart");
    const card = page.locator('[data-slot="card"]').filter({ has: chart });
    const summary = card.locator("summary").filter({ hasText: "Event details (3)" });
    await expect(summary).toBeVisible();
    await summary.focus();
    await page.keyboard.press("Enter");
    const table = card.getByRole("table", { name: "Anomaly event details" });
    await expect(table).toBeVisible();
    await expect(table.getByRole("row")).toHaveCount(4);
    for (const column of ["Event time", "Type", "Readings", "Telemetry sample time", "Value", "Offset"]) {
      await expect(table.getByRole("columnheader", { name: column, exact: true })).toBeVisible();
    }
    await expect(table.getByRole("row").filter({ hasText: "drift" })).toContainText("No nearby telemetry sample");
    await expect(table.getByRole("row").filter({ hasText: "multivariate" })).toContainText(/context/iu);
    const pixels = await readCanvas(chart);
    expect(pixels.orange.count).toBeGreaterThan(10);
    expect(pixels.topRed.count).toBeGreaterThan(10);
    // The reading spans the shared time axis, from its first sample to its last.
    const domain = pixels.reading;
    const span = domain.right - domain.left;
    expect(Math.abs((pixels.orange.left + pixels.orange.right) / 2 - domain.left - span / 240)).toBeLessThan(3);
    expect(Math.abs((pixels.topRed.left + pixels.topRed.right) / 2 - domain.left - span / 6)).toBeLessThan(3);

  });

  test("linked chart navigation mirrors inspection and returns every chart to live", async ({ page }) => {
    await installMockApi(page, "mixed", "light", [SENSOR, "systemCurrent"]);
    await page.goto(`/details/${DEVICE_ID}`);
    const voltageCard = page.locator('[data-slot="card"]').filter({ hasText: "System Voltage" }).first();
    const currentCard = page.locator('[data-slot="card"]').filter({ hasText: "System Current" }).first();
    const voltageChart = voltageCard.getByTestId("telemetry-echart");
    const currentChart = currentCard.getByTestId("telemetry-echart");
    await expect(voltageChart).toBeVisible();
    await currentCard.scrollIntoViewIfNeeded();
    await expect(currentChart).toBeVisible();
    await zoomChart(page, voltageCard);
    await expect(currentCard.getByRole("button", { name: "Return to live" })).toBeHidden();
    await page.getByRole("button", { name: "Link chart navigation" }).click();
    await expect(page.getByRole("button", { name: "Unlink chart navigation" })).toHaveAttribute("aria-pressed", "true");
    await currentCard.scrollIntoViewIfNeeded();
    await expect(currentCard.getByRole("button", { name: "Return to live" })).toBeVisible();
    await currentCard.getByRole("button", { name: "Return to live" }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("button", { name: "Return to live" })).toHaveCount(0);
  });

  test("a range-boundary event keeps its outside-range sample context visible", async ({ page }, testInfo) => {
    await installMockApi(page, "static", "light");
    const points = [
      { timestamp: timestamp(3), created: timestamp(3), value: 1_000 },
      { timestamp: timestamp(7), created: timestamp(7), value: 230 },
      { timestamp: timestamp(3_604), created: timestamp(3_604), value: 231 },
    ];
    await page.route(`**/v1/readings/${SENSOR}/measurements*`, (route) =>
      fulfillJson(route, new URL(route.request().url()).searchParams.has("after_created") ? [] : points),
    );
    await page.route("**/v1/evidence/chart?*", (route) => fulfillJson(route, []));
    await page.route("**/v1/alarms?*", (route) => fulfillJson(route, [
      { ...anomalies[0], alarm_id: "range-boundary", timestamp: timestamp(4) },
    ]));
    await page.goto(`/details/${DEVICE_ID}`);
    const chart = page.getByTestId("telemetry-echart");
    const card = page.locator('[data-slot="card"]').filter({ has: chart });
    await expect(chart).toBeVisible();
    await expect.poll(async () => (await readCanvas(chart)).orange.count).toBeGreaterThan(10);
    await card.getByRole("button", { name: "Past hour" }).click();
    await card.locator("summary").filter({ hasText: "Event details (1)" }).click();
    const table = card.getByRole("table", { name: "Anomaly event details" });
    await expect(table).toContainText("1000");
    await expect(table).toContainText("-1000 ms");

    await expect.poll(async () => (await readCanvas(chart)).orange.count).toBeGreaterThan(10);
    const pixels = await readCanvas(chart);
    expect(pixels.orange.top).toBeGreaterThanOrEqual(0);
    expect(pixels.orange.bottom).toBeLessThan(pixels.height / 3);
    expect(pixels.orange.right - pixels.orange.left).toBeGreaterThan(3);
    expect(pixels.orange.bottom - pixels.orange.top).toBeGreaterThan(3);
    const screenshotPath = testInfo.outputPath("range-boundary-context.png");
    await card.screenshot({ path: screenshotPath });
    await testInfo.attach("range boundary context", { path: screenshotPath, contentType: "image/png" });
  });
});
