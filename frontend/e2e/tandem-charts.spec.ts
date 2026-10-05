import { expect, test, type Locator, type Page, type Route } from "@playwright/test";

import { zoomChart } from "./helpers/chart";

const CHARGER_ID = "e2e-tandem";
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
  service_id: "static-service",
  timestamp: timestamp(seconds),
  created: timestamp(seconds + 30),
  sequence_number: index + 1,
  sensor_set: [SENSOR],
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
  service_id: serviceId,
  timestamp: timestamp(seconds),
  created: timestamp(seconds + 30),
  sequence_number: sequence,
  sensor_set: [SENSOR],
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

const anomalies = [
  {
    anomaly_id: "coincident-a",
    charger_id: CHARGER_ID,
    timestamp: timestamp(1),
    telemetry_type: SENSOR,
    anomaly_type: "spike",
    anomaly_value: 0.01,
    value_type: "tail_pvalue",
    sensor_set: [SENSOR],
  },
  {
    anomaly_id: "coincident-b",
    charger_id: CHARGER_ID,
    timestamp: timestamp(1),
    telemetry_type: "__multivariate__",
    anomaly_type: "multivariate",
    anomaly_value: 0.02,
    value_type: "conformal_pvalue",
    sensor_set: [SENSOR, "systemCurrent"],
  },
  {
    anomaly_id: "unmatched",
    charger_id: CHARGER_ID,
    timestamp: timestamp(40),
    telemetry_type: SENSOR,
    anomaly_type: "drift",
    anomaly_value: 0.005,
    value_type: "tail_pvalue",
    sensor_set: [SENSOR],
  },
];

const fulfillJson = (route: Route, json: unknown) => route.fulfill({
  json,
  headers: {
    "access-control-allow-origin": "*",
    "access-control-allow-headers": "authorization, content-type",
    "access-control-allow-methods": "GET, OPTIONS",
  },
});

const installMockApi = async (
  page: Page,
  mode: EvidenceMode,
  theme: Theme,
  sensors: string[] = [SENSOR],
) => {
  let published = false;
  const evidence = mode === "static" ? staticEvidence : mode === "adaptive" ? adaptiveEvidence : [...staticEvidence, ...adaptiveEvidence];

  await page.addInitScript((preferredTheme) => {
    const payload = btoa(JSON.stringify({ sub: "1", user_id: 1, exp: 4_102_444_800 }));
    localStorage.setItem("auth_token", `e2e.${payload}.signature`);
    localStorage.setItem("token_storage_type", "localStorage");
    localStorage.setItem("vite-ui-theme", preferredTheme);
  }, theme);

  await page.route("**/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const incremental = url.searchParams.has("after_created");
    if (route.request().method() === "OPTIONS") {
      return route.fulfill({ status: 204, headers: {
        "access-control-allow-origin": "*", "access-control-allow-headers": "authorization, content-type",
        "access-control-allow-methods": "GET, OPTIONS",
      } });
    }
    switch (url.pathname.replace(/^\/api(?=\/v1\/)/u, "")) {
      case "/v1/members/me":
        return fulfillJson(route, {
          id: 1, email: "tandem@example.test", role: "admin", is_active: true,
          is_verified: true, created_at: timestamp(0),
        });
      case "/v1/sources":
        return fulfillJson(route, { catalog: { sources: [{ chargers: [{
          id: CHARGER_ID, sensors: sensors.map((key) => ({ key, category: key === SENSOR ? "Voltage" : "Current" })),
        }] }] } });
      case `/v1/telemetry/${CHARGER_ID}/type`:
        return fulfillJson(route, sensors);
      case `/v1/telemetry/${CHARGER_ID}/data`:
        return fulfillJson(route, incremental ? published ? [{ timestamp: timestamp(300), created: timestamp(301), value: 233 }] : [] : telemetry);
      case "/v1/anomalies/count":
        return fulfillJson(route, { count: anomalies.length });
      case "/v1/anomalies":
        return fulfillJson(route, [...anomalies, anomalies[0]]);
      case "/v1/monitors/all":
        return fulfillJson(route, []);
      case "/v1/monitors/evidence/chart":
        return fulfillJson(route, incremental ? published && mode !== "static" ? [adaptiveRow("adaptive-z", 300, 3)] : [] : evidence);
      default:
        throw new Error(`Unexpected mocked API request: ${url.pathname}`);
    }
  });

  return {
    publish: async () => {
      published = true;
      const response = page.waitForResponse((candidate) =>
        candidate.url().includes(`/telemetry/${CHARGER_ID}/data`) &&
        candidate.url().includes("after_created"),
      );
      await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
      await response;
    },
  };
};

type PixelGlyph = { count: number; left: number; right: number; top: number; bottom: number };
type CanvasReadout = {
  width: number;
  height: number;
  tintAlpha: number;
  tintBands: Array<{ left: number; right: number; top: number; bottom: number; gapPixels: number }>;
  orange: PixelGlyph;
  topRed: PixelGlyph;
  overflowPixels: number;
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
  const rowCounts = new Uint32Array(height);
  const histogram = new Uint32Array(256);
  const orange = { count: 0, left: width, right: 0, top: height, bottom: 0 };
  const tint = (offset: number) => pixels[offset + 3]! >= 18 && pixels[offset + 3]! <= 60 &&
    pixels[offset]! > pixels[offset + 1]! + 40 && Math.abs(pixels[offset + 1]! - pixels[offset + 2]!) < 12;
  const red = (offset: number) => pixels[offset + 3]! >= 170 &&
    pixels[offset]! > pixels[offset + 1]! + 40 && Math.abs(pixels[offset + 1]! - pixels[offset + 2]!) < 20;
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const offset = (y * width + x) * 4;
      if (tint(offset)) {
        rowCounts[y]! += 1;
        histogram[pixels[offset + 3]!]! += 1;
      }
      if (pixels[offset + 3]! >= 140 && pixels[offset]! > pixels[offset + 1]! + 60 && pixels[offset + 1]! > pixels[offset + 2]! + 60) {
        orange.count += 1;
        orange.left = Math.min(orange.left, x);
        orange.right = Math.max(orange.right, x);
        orange.top = Math.min(orange.top, y);
        orange.bottom = Math.max(orange.bottom, y);
      }
    }
  }
  const rows: Array<{ first: number; last: number }> = [];
  for (let y = 0; y < height; y += 1) {
    if (rowCounts[y]! < 4 * scaleX) continue;
    const previous = rows[rows.length - 1];
    if (previous && y - previous.last <= 3 * scaleY) previous.last = y;
    else rows.push({ first: y, last: y });
  }
  const tintBands = rows.filter((row) => row.last - row.first >= 3 * scaleY).map((row) => {
    const columns = new Uint32Array(width);
    let left = width;
    let right = 0;
    for (let y = row.first; y <= row.last; y += 1) {
      for (let x = 0; x < width; x += 1) {
        if (!tint((y * width + x) * 4)) continue;
        columns[x]! += 1;
        left = Math.min(left, x);
        right = Math.max(right, x);
      }
    }
    // The fixture's unevaluated observation is one quarter through the time range.
    const gapColumn = Math.round(left + (right - left) / 4);
    return { left: left / scaleX, right: right / scaleX, top: row.first / scaleY,
      bottom: row.last / scaleY, gapPixels: columns[gapColumn] ?? 0 };
  });
  let tintAlpha = 0;
  for (let alpha = 1; alpha < histogram.length; alpha += 1) {
    if (histogram[alpha]! > histogram[tintAlpha]!) tintAlpha = alpha;
  }
  const topRed = { count: 0, left: width, right: 0, top: height, bottom: 0 };
  let overflowPixels = 0;
  const firstBand = tintBands[0];
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      if (!red((y * width + x) * 4)) continue;
      if (y / scaleY < (firstBand?.top ?? height / scaleY) - 20) {
        topRed.count += 1;
        topRed.left = Math.min(topRed.left, x);
        topRed.right = Math.max(topRed.right, x);
        topRed.top = Math.min(topRed.top, y);
        topRed.bottom = Math.max(topRed.bottom, y);
      }
      if (firstBand && Math.abs(x / scaleX - firstBand.right) < 6 &&
        y / scaleY >= firstBand.top - 6 && y / scaleY <= firstBand.top + 12) overflowPixels += 1;
    }
  }
  const normalize = (glyph: typeof orange) => ({ count: glyph.count,
    left: glyph.count ? glyph.left / scaleX : 0, right: glyph.right / scaleX,
    top: glyph.count ? glyph.top / scaleY : 0, bottom: glyph.bottom / scaleY });
  return { width: canvas.clientWidth, height: canvas.clientHeight, tintAlpha, tintBands,
    orange: normalize(orange), topRed: normalize(topRed), overflowPixels };
});

const screenshotCard = async (page: Page, card: Locator, path: string) => {
  await page.locator("header").evaluateAll((headers) => {
    headers.forEach((header) => { header.style.visibility = "hidden"; });
  });
  await card.screenshot({ path });
};

test.use({ video: "off", trace: "off" });

test.describe("Tandem anomaly chart regression", () => {
  test.use({
    storageState: { cookies: [], origins: [] },
    timezoneId: "UTC", colorScheme: "light", reducedMotion: "reduce",
    viewport: { width: 1440, height: 1100 },
  });

  for (const mode of ["static", "adaptive", "mixed"] as const) {
    for (const theme of ["light", "dark"] as const) {
      test(`${mode} alarm regions render in ${theme} at desktop and narrow widths`, async ({ page }, testInfo) => {
        await installMockApi(page, mode, theme);
        await page.goto(`/details/${CHARGER_ID}`);
        const chart = page.getByTestId("telemetry-echart");
        const card = page.locator('[data-slot="card"]').filter({ has: chart });
        await expect(chart).toBeVisible();
        await expect(chart.locator("canvas")).toHaveCount(1);
        await expect(chart).toHaveAttribute("aria-label", mode === "mixed"
          ? /1 logarithmic static-evidence series.*1 linear adaptive score series/u
          : mode === "static" ? /1 logarithmic static-evidence series/u : /1 linear adaptive score series/u);
        if (mode !== "adaptive") {
          await expect(card.getByText(/Beyond numeric range/u)).toBeVisible();
        }
        await expect(card.getByText(/Shaded values|unshaded gaps|threshold unavailable/iu)).toHaveCount(0);
        await expect(chart).toHaveAttribute("aria-label", /alarm region/u);

        for (const width of [1440, 390, 320]) {
          await page.setViewportSize({ width, height: width === 1440 ? 1100 : 1000 });
          await card.scrollIntoViewIfNeeded();
          await expect.poll(async () => (await readCanvas(chart)).tintBands.length).toBe(mode === "mixed" ? 2 : 1);
          const pixels = await readCanvas(chart);
          expect(pixels.tintAlpha).toBe(theme === "light" ? 26 : 36);
          for (const band of pixels.tintBands) {
            expect(band.bottom - band.top).toBeGreaterThan(6);
            expect(band.gapPixels).toBe(0);
            expect(Math.abs(band.left - pixels.tintBands[0]!.left)).toBeLessThanOrEqual(2);
            expect(Math.abs(band.right - pixels.tintBands[0]!.right)).toBeLessThanOrEqual(2);
          }
          if (mode !== "adaptive") expect(pixels.overflowPixels).toBeGreaterThan(10);
          const box = await chart.boundingBox();
          expect(box).not.toBeNull();
          expect(box!.width).toBeLessThanOrEqual(width);
          expect(box!.width).toBeGreaterThan(width === 320 ? 200 : 250);
          expect(await card.evaluate((element) => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1);
          const screenshotPath = testInfo.outputPath(`${mode}-${theme}-${width}.png`);
          await screenshotCard(page, card, screenshotPath);
          await testInfo.attach(`${mode} ${theme} ${width}px`, { path: screenshotPath, contentType: "image/png" });
        }
      });
    }
  }

  test("detector controls support keyboard focus and retain selection through polling, zoom, and theme changes", async ({ page }) => {
    const api = await installMockApi(page, "mixed", "light");
    await page.goto(`/details/${CHARGER_ID}`);
    const chart = page.getByTestId("telemetry-echart");
    const card = page.locator('[data-slot="card"]').filter({ has: chart });
    const staticDetector = card.getByRole("combobox", { name: "Static detector" });
    const adaptiveDetector = card.getByRole("combobox", { name: "Adaptive detector" });
    await expect(staticDetector).toBeVisible();
    await expect(adaptiveDetector).toBeVisible();
    await expect(staticDetector).toHaveValue("restarted-martingale:static-service");
    await expect(adaptiveDetector.locator("option:checked")).toContainText("adaptive-a");
    await staticDetector.focus();
    await expect(staticDetector).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(adaptiveDetector).toBeFocused();
    await adaptiveDetector.selectOption("adaptive-score:adaptive-z");
    await expect(adaptiveDetector.locator("option:checked")).toContainText("adaptive-z");
    const selected = await adaptiveDetector.inputValue();
    await expect(card.getByText(/Anomaly score:\s*3/u)).toBeVisible();
    await expect(card.getByText(/Anomaly score:\s*7/u)).toHaveCount(0);
    await zoomChart(page, card);
    await api.publish();
    await expect(card.getByText("New data available")).toBeVisible();
    await expect(adaptiveDetector).toHaveValue(selected);
    await expect(card.getByRole("button", { name: "Return to live" })).toBeVisible();
    await page.getByRole("button", { name: "Toggle theme" }).click();
    await page.getByRole("menuitem", { name: "Dark" }).click();
    await expect(page.locator("html")).toHaveClass(/dark/u);
    await expect(adaptiveDetector).toHaveValue(selected);
    await expect(card.getByRole("button", { name: "Return to live" })).toBeVisible();
    await card.getByRole("button", { name: "Past hour" }).click();
    await expect(adaptiveDetector).toHaveValue(selected);
    await expect(card.getByRole("button", { name: "Return to live" })).toBeHidden();
  });

  test("event details keep coincident events and unmatched timestamps inspectable by keyboard", async ({ page }) => {
    await installMockApi(page, "mixed", "light");
    await page.goto(`/details/${CHARGER_ID}`);
    const chart = page.getByTestId("telemetry-echart");
    const card = page.locator('[data-slot="card"]').filter({ has: chart });
    const summary = card.locator("summary").filter({ hasText: "Event details (3)" });
    await expect(summary).toBeVisible();
    await summary.focus();
    await page.keyboard.press("Enter");
    const table = card.getByRole("table", { name: "Anomaly event details" });
    await expect(table).toBeVisible();
    await expect(table.getByRole("row")).toHaveCount(4);
    for (const column of ["Event time", "Type", "Sensors", "Telemetry sample time", "Value", "Offset"]) {
      await expect(table.getByRole("columnheader", { name: column, exact: true })).toBeVisible();
    }
    await expect(table.getByRole("row").filter({ hasText: "drift" })).toContainText("No nearby telemetry sample");
    await expect(table.getByRole("row").filter({ hasText: "multivariate" })).toContainText(/context/iu);
    const pixels = await readCanvas(chart);
    expect(pixels.orange.count).toBeGreaterThan(10);
    expect(pixels.topRed.count).toBeGreaterThan(10);
    const domain = pixels.tintBands[0]!;
    const span = domain.right - domain.left;
    expect(Math.abs((pixels.orange.left + pixels.orange.right) / 2 - domain.left - span / 240)).toBeLessThan(3);
    expect(Math.abs((pixels.topRed.left + pixels.topRed.right) / 2 - domain.left - span / 6)).toBeLessThan(3);

  });

  test("linked chart navigation mirrors inspection and returns every chart to live", async ({ page }) => {
    await installMockApi(page, "mixed", "light", [SENSOR, "systemCurrent"]);
    await page.goto(`/details/${CHARGER_ID}`);
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
    await page.route(`**/v1/telemetry/${CHARGER_ID}/data*`, (route) =>
      fulfillJson(route, new URL(route.request().url()).searchParams.has("after_created") ? [] : points),
    );
    await page.route("**/v1/monitors/evidence/chart?*", (route) => fulfillJson(route, []));
    await page.route("**/v1/anomalies?*", (route) => fulfillJson(route, [
      { ...anomalies[0], anomaly_id: "range-boundary", timestamp: timestamp(4) },
    ]));
    await page.goto(`/details/${CHARGER_ID}`);
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
    await screenshotCard(page, card, screenshotPath);
    await testInfo.attach("range boundary context", { path: screenshotPath, contentType: "image/png" });
  });
});
