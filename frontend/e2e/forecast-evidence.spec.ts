import { expect, test } from "@playwright/test";
import { installSidebarMockApi } from "./helpers/sidebarMockApi";
import { fulfillJson } from "./helpers/detailsMockApi";

const start = Date.parse("2026-11-11T12:00:00Z");
const at = (index: number) => new Date(start + index * 1000).toISOString();
const value = (index: number) => 50 + Math.sin(index / 16) * 0.025 + Math.cos(index * 2) * 0.004;
const telemetry = Array.from({ length: 240 }, (_, index) => ({ timestamp: at(index), value: value(index) }));
const evidence = telemetry.slice(24).map((point, offset) => ({
  monitor_id: "forecast-monitor", timestamp: point.timestamp, created: point.timestamp, sequence_number: offset + 1,
  reading_ids: ["frequency"], input_timestamps: { frequency: point.timestamp }, strategy: "adaptive_stream", model_type: "forecast.timestral",
  anomaly_score: 1, threshold: 2, alarm: offset === 90, restarted_martingale: null,
  detector_inputs: [{ detector_id: null, inputs: { frequency: point.value } }],
  forecasts: [1, 12].map(lead => ({ detector_id: "timestral", target: "frequency", slot: "signal", lead,
    expected: value(offset + 24 - lead), lower: value(offset + 24 - lead) - 0.012, upper: value(offset + 24 - lead) + 0.012,
    issued: { issued_at: at(offset + 24.15), origin_step: offset + 25, origin_time: point.timestamp,
      time_basis: "estimated_cadence", step_seconds: 1,
      points: Array.from({ length: lead }, (_, index) => ({ lead: index + 1, target_step: offset + 26 + index,
        target_time: at(offset + 25 + index), expected: value(offset + 25 + index),
        lower: index + 1 === lead ? value(offset + 25 + index) - 0.012 : null,
        upper: index + 1 === lead ? value(offset + 25 + index) + 0.012 : null })),
    } })),
}));
const definition = { schema_version: 2, input_slots: [{ id: "signal", label: "Frequency" }], settings: {},
  nodes: [{ id: "input", kind: "source", component: "source.aligned", params: {} },
    { id: "timestral", kind: "detector", component: "detector:forecast.timestral", params: {} },
    { id: "calibrate", kind: "calibration", component: "calibrate.nexcp", params: {} }],
  edges: [{ source: "input", target: "timestral" }, { source: "timestral", target: "calibrate" }] };

for (const theme of ["light", "dark"] as const) {
  test(`forecast overlay and lead diagnostics in ${theme}`, async ({ page }, testInfo) => {
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.setViewportSize({ width: 1440, height: 1200 });
    await installSidebarMockApi(page, { theme, favourites: [] });
    await page.route("**/v1/**", async route => {
      const url = new URL(route.request().url());
      const path = url.pathname.replace(/^\/api(?=\/v1\/)/u, "");
      if (path === "/v1/catalogue") return fulfillJson(route, {
        revision: 1, can_edit: true, storage_origin: "saved",
        document: { format: "aberration-system", schema_version: 1, label: "Forecast fixture", default_policy: { mode: "off" },
          brokers: [{ id: "broker", label: "Meter", host: "example.invalid", protocol: "mqtt", port: 1883, transport: "tcp", tls: false }],
          devices: [], groups: [], readings: [{ id: "frequency", label: "Frequency", broker_id: "broker", topic: "frequency",
            category: "Other", value_type: "number", unit: "Hz" }] },
        runtime: { mode: "configured_only", bindings: { frequency: { policy: { mode: "original", interval_seconds: 1 } } } },
      });
      if (path === "/v1/monitors/overview") return fulfillJson(route, { authoring_enabled: false, monitors: [{
        id: "forecast-monitor", display_name: "Timestral / Frequency", reading_ids: ["frequency"], model_type: "forecast.timestral",
        monitoring_strategy: "adaptive_stream", active: true,
        operational_status: { stage: "operational", is_stale: false, message_count: 240, processed_message_count: 216, updated_at: at(239) },
      }] });
      if (path === "/v1/monitors/forecast-monitor") return fulfillJson(route, { configuration: { monitoring: {}, performance_config: {} } });
      if (path === "/v1/monitors/forecast-monitor/pipeline") return fulfillJson(route, { definition, layout: { nodes: {} }, history: [],
        run: { id: "run", execution: { definition, bindings: [{ slot_id: "signal", reading_id: "frequency", unit: "Hz" }] } },
        validation: { valid: true, definition, features: { input: [{ name: "frequency", raw: true, slots: ["signal"] }] } },
      });
      if (path === "/v1/evidence/chart") return fulfillJson(route, url.searchParams.has("after_created") ? [] : evidence);
      if (path === "/v1/readings/frequency/measurements") return fulfillJson(route, url.searchParams.has("after_created") ? [] : telemetry);
      return route.fallback();
    });
    await page.goto("/?service=forecast-monitor&tab=evidence");
    const history = page.getByRole("region", { name: "Monitoring history", exact: true });
    await expect(history.getByRole("heading", { name: "Forecast and deviations" })).toBeVisible();
    await expect(history.getByText(/Shaded: NexCP interval/)).toBeVisible();
    const chart = history.getByRole("group", { name: "Chart navigation", exact: true });
    await expect(chart.locator("canvas")).toBeVisible();
    await expect(chart).toHaveCSS("height", "416px");
    const selector = history.getByRole("combobox", { name: "Forecast lead" });
    await expect(selector).toHaveValue("1");
    await history.getByRole("button", { name: "Zoom in", exact: true }).click();
    await selector.selectOption("12");
    await expect(selector).toHaveValue("12");
    await expect(history.getByRole("button", { name: "Return to live", exact: true })).toBeEnabled();
    await history.getByRole("button", { name: "Return to live", exact: true }).click();
    await expect(chart).toHaveCSS("height", "416px");
    await history.screenshot({ path: testInfo.outputPath(`forecast-${theme}.png`) });
    const mode = history.getByRole("button", { name: /^Forecast view:/ });
    await expect(mode).toHaveAccessibleName("Forecast view: Overlay. Switch to Forecast ahead");
    await mode.click();
    await expect(mode).toHaveAccessibleName("Forecast view: Forecast ahead. Switch to Data only");
    await expect(chart).toHaveCSS("height", "416px");
    await history.screenshot({ path: testInfo.outputPath(`forecast-ahead-${theme}.png`) });
    const bounds = await chart.boundingBox();
    await page.mouse.move(bounds!.x + bounds!.width - 21, bounds!.y + 110);
    await chart.screenshot({ path: testInfo.outputPath(`forecast-tooltip-${theme}.png`) });
    await history.getByRole("button", { name: "Zoom in", exact: true }).click();
    await mode.focus();
    await page.keyboard.press("Enter");
    await expect(mode).toHaveAccessibleName("Forecast view: Data only. Switch to Overlay");
    await expect(history.getByRole("button", { name: "Return to live", exact: true })).toBeEnabled();
    await expect(selector).toHaveValue("12");
    await history.getByRole("button", { name: "Return to live", exact: true }).click();
    await history.screenshot({ path: testInfo.outputPath(`forecast-data-${theme}.png`) });
    await history.getByRole("checkbox", { name: "Show residuals" }).uncheck();
    await expect(chart).toHaveCSS("height", "268px");
    await mode.click();
    await expect(mode).toHaveAccessibleName("Forecast view: Overlay. Switch to Forecast ahead");
    await expect(chart).toHaveCSS("height", "268px");
    await history.getByRole("checkbox", { name: "Show residuals" }).check();
    await history.getByRole("checkbox", { name: "Show detector scores" }).check();
    await expect(chart).toHaveCSS("height", "564px");
    await history.getByRole("checkbox", { name: "Show detector scores" }).uncheck();
    await history.getByText("Latest forecast results · 2 leads", { exact: true }).click();
    await expect(history.getByRole("table")).toBeVisible();
    await history.getByRole("button", { name: "Frequency (Hz) · 1 update ahead", exact: true }).click();
    await expect(selector).toHaveValue("1");
    await history.getByText("Latest forecast results · 2 leads", { exact: true }).click();
    await selector.selectOption("12");
    await page.setViewportSize({ width: 390, height: 844 });
    await mode.click();
    await expect(mode).toHaveAccessibleName("Forecast view: Forecast ahead. Switch to Data only");
    await history.getByRole("heading", { name: "Forecast and deviations" }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath(`forecast-${theme}-mobile.png`) });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    expect(errors).toEqual([]);
  });
}
