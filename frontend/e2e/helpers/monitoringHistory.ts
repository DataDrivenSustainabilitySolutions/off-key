import { expect, type APIRequestContext, type Page, type TestInfo } from "@playwright/test";
import { setAppearance } from "./appearance";

type Evidence = { service_id: string; strategy: string; model_type?: string; anomaly_score?: number | null;
  input_timestamps: Record<string, string>; sequence_number: number };

/** Inspect the real collector/worker/database results, without replacing API responses. */
export async function inspectMonitoringHistory({ page, api, headers, serviceId, entityId, strategy, testInfo }: {
  page: Page; api: APIRequestContext; headers: Record<string, string>; serviceId: string;
  entityId: string; strategy: "adaptive_stream" | "static_baseline"; testInfo: TestInfo;
}) {
  const response = await api.get(`/api/v1/monitors/evidence/chart?charger_id=${entityId}&service_id=${serviceId}`, { headers });
  expect(response.ok(), await response.text()).toBe(true);
  const evidence = await response.json() as Evidence[];
  expect(evidence.length).toBeGreaterThan(0);
  expect(evidence.every(row => row.service_id === serviceId)).toBe(true);
  expect(evidence.every(row => Object.keys(row.input_timestamps).length === 3)).toBe(true);
  if (strategy === "adaptive_stream") {
    expect(evidence.every(row => row.model_type === "aberrant_online_isolation_forest")).toBe(true);
    expect(evidence.some(row => Number.isFinite(row.anomaly_score))).toBe(true);
  }
  await page.getByRole("tab", { name: "Evidence", exact: true }).click();
  const history = page.getByRole("region", { name: "Monitoring history", exact: true });
  await expect(history).toContainText("Joint result across all 3 inputs");
  const chart = history.getByRole("img", { name: /^3 displayed readings of 3 monitored inputs:/ });
  await expect(chart).toBeVisible();
  const latest = history.getByLabel("Latest detector result", { exact: true });
  await expect(latest).toContainText(strategy === "adaptive_stream" ? "Joint anomaly score" : "Restarted e-process");
  await expect(history).toContainText("Threshold:");
  await setAppearance(page, "Light");
  // Each input curve must actually paint inside its plot, excluding titles/axes.
  await expect.poll(() => chart.evaluate(element => {
    const canvas = element.querySelector("canvas");
    if (!canvas) return [];
    const context = canvas.getContext("2d");
    if (!context) return [];
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
    const scale = canvas.width / canvas.clientWidth;
    const colors = [[58, 126, 114], [113, 97, 181], [179, 107, 50]];
    return colors.map((color, index) => {
      let count = 0;
      for (let y = Math.ceil((28 + index * 148) * scale); y < (128 + index * 148) * scale; y++) {
        for (let x = Math.ceil(53 * scale); x < canvas.width - 18 * scale; x++) {
          const offset = (y * canvas.width + x) * 4;
          if (pixels[offset + 3]! > 100 && color.every((channel, component) => Math.abs(channel - pixels[offset + component]!) < 10)) count++;
        }
      }
      return count > 5;
    });
  })).toEqual([true, true, true]);
  await history.screenshot({ path: testInfo.outputPath(`monitoring-history-${strategy}-desktop.png`) });
  await history.getByText("Displayed readings · 3 of 3", { exact: true }).click();
  await history.getByRole("checkbox", { name: /^current\b/ }).uncheck();
  await expect(history.getByRole("img", { name: /^2 displayed readings of 3 monitored inputs:/ })).toBeVisible();
  await expect(latest).toContainText(strategy === "adaptive_stream" ? "Joint anomaly score" : "Restarted e-process");
  await expect(history).toContainText("Joint result across all 3 inputs");
  await history.getByRole("checkbox", { name: /^current\b/ }).check();
  await history.getByRole("button", { name: "Zoom in", exact: true }).click();
  await expect(history.getByRole("button", { name: "Return to live", exact: true })).toBeVisible();
  await history.getByRole("button", { name: "Return to live", exact: true }).click();
  await history.getByText("Displayed readings · 3 of 3", { exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await setAppearance(page, "Dark");
  await expect(chart).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await history.screenshot({ path: testInfo.outputPath(`monitoring-history-${strategy}-mobile.png`) });
  await page.setViewportSize({ width: 1600, height: 1100 });
  await setAppearance(page, "Light");
}
